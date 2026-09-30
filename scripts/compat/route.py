#!/usr/bin/env python3
"""Level 3 probe: do a skill's utterances reach it on a normal install?

Runs INSIDE the shard's routing venv: the channel stack, the installer's
default skills (the baseline, see baseline.py) and every skill of the shard
that loaded at level 2. One MiniCroft per language serves the whole shard,
so the baseline is booted once per shard and language, not once per skill
(issue #6: the fleet routing suite takes 5h+ when every skill gets its own
boot). One language per boot, because the session language does not select
the intent container (ovos-test-harness skills_fleet, measured on
fuster-quotes): a row needs a MiniCroft built for its own language.

Rows are the golden-utterance format `ovoscope golden` runs (utterance,
lang, skill_id, expected_intent or intent_label, needs_manual). Golden and
generated rows come in as separate runs and are counted separately; this
script never looks at where a row came from, only at which run it is in.

Who took a row (the claimant) is read from the bus the way
ovos-test-harness's fleet suite does it: only messages on the row's own
session, `ovos.intent.unmatched` means nobody, else the first
`<skill_id>:<intent>` topic, else the skill_id on a `speak`.

  hit        the row's skill took it (and the expected intent, when given)
  wrong_intent  the row's skill took it with another intent
  baseline   a default skill took it: intent theft a real device would see
  unhandled  nobody took it, or only a pipeline stage without a skill
  neighbour  another skill of this shard took it (one that is not in
             `counted_ids` of the manifest, see below). Shards are cut by
             plan.py, not by users, so this is shown as a collision on the
             detail page and left out of the score.
  hang       nobody claimed it and a pipeline stage did not return within
             --timeout (typically a common-query provider that blocks); a
             miss, with the stage it was stuck in
  asked      (not an outcome of its own) the skill that took the row asked
             a follow-up question; it is answered with "cancel" in the
             row's session (see ASK_ENABLE) and the row is judged as usual,
             so a question from the row's own skill is a hit. `asked`
             counts those hits.

The Klondike job (issue #13) routes the profile's own store skills and
every other skill tested against the profile in one core. Its manifest
lists the profile's skill ids as `counted_ids`: a sentence one of those
takes counts as "baseline" (a real device with the profile would see it),
while one taken by another tested skill stays a "neighbour", not counted.
`uncounted_ids` names tested skills that are loaded but have no rows of
their own (so are not in the manifest's items): they are neighbours too.

Output: one JSON object, rewritten after every row, so a run killed by the
outer timeout still says how far it got. With --budget, rows past it are
left out and the status is "partial" (issue #15); row_seconds says how long
rows took (median, p95, max).

A row waits for its handler to return (or --timeout). Ending it as soon as
the claim is known was tried for #15 and dropped: a handler still running
from one row changed the verdicts of later rows (weather's humidity
sentences went from hit to hang in both runs that did it, and in none that
did not).
"""
import argparse
import itertools
import json
import os
import sys
import threading
import time
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from probe import boot, modern_driver, same_language  # noqa: E402

EOF_TYPES = {"ovos.utterance.handled", "mycroft.skill.handler.complete",
             "complete_intent_failure", "ovos.intent.unmatched"}
CAPTURE_SETTLE = 0.4
# A handler that asks the user something (get_response / ask_yesno) waits
# for an answer that never comes: ovos-workshop before 9.x waits forever
# (num_retries=-1, fixed upstream in ovos-workshop#514). In this core that
# blocks the row's emit thread until --timeout and leaves the thread behind
# for the rest of the run. So a question is answered with "cancel", sent
# with the FULL session from the enable message's context: the response
# mode lives in that session, and a cancel carrying only the session_id is
# routed as a fresh utterance and frees nothing (verified live,
# ovos-tui-client#54). The row then counts as handled by whoever asked.
ASK_ENABLE = "skill.converse.get_response.enable"
ASK_DISABLE = "skill.converse.get_response.disable"
ASK_GRACE = 0.5       # an answer the handler itself provides (no real wait)
ASK_RELEASE = 5.0     # how long the cancel may take to release the handler
MAX_MISSES = 25
_SESSION_SEQ = itertools.count()


def read_rows(path):
    rows = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            try:
                d = json.loads(line)
            except ValueError:
                continue
            if isinstance(d, dict) and d.get("utterance") and d.get("lang"):
                rows.append(d)
    return rows


def installed_skill_ids():
    from ovos_plugin_manager.skills import find_skill_plugins
    return set(find_skill_plugins())


def available_stages(pipeline):
    """(stages whose plugin is installed, stages dropped). Unknown when OPM
    cannot list pipeline plugins: then everything is kept and MiniCroft
    logs what it could not serve."""
    try:
        from ovos_plugin_manager.pipeline import find_pipeline_plugins
        installed = set(find_pipeline_plugins())
    except Exception:  # noqa: BLE001
        return list(pipeline), []
    keep, dropped = [], []
    for stage in pipeline:
        base = stage
        for suffix in ("-high", "-medium", "-low"):
            if stage.endswith(suffix):
                base = stage[: -len(suffix)]
                break
        (keep if base in installed else dropped).append(stage)
    return keep, dropped


def warm_models(croft, pipeline):
    """Load lazy models (m2v) before the first row, like `ovoscope golden`
    does; a stage whose model cannot load is dropped from the row sessions
    and reported, not blamed on the skill."""
    svc = getattr(croft, "intents", None)
    dropped = []
    for pid, plugin in (getattr(svc, "pipeline_plugins", {}) or {}).items():
        ensure = getattr(plugin, "_ensure_model", None)
        if ensure is None:
            continue
        try:
            ensure(background_ok=False)
        except Exception as e:  # noqa: BLE001
            dropped += [s for s in pipeline if s.startswith(pid)]
            print(f"warning: {pid} model did not load: {e}", file=sys.stderr)
    return [s for s in pipeline if s not in dropped], dropped


def _session_of(msg):
    sess = (msg.context or {}).get("session") or {}
    return sess.get("session_id") or "" if isinstance(sess, dict) else ""


def capture(croft, utterance, lang, pipeline, timeout):
    from ovos_bus_client.message import Message
    from ovos_bus_client.session import Session
    recs = []

    def rec(serialized):
        if isinstance(serialized, Message):
            recs.append(serialized)
            return
        try:
            recs.append(Message.deserialize(serialized))
        except Exception:  # noqa: BLE001
            pass

    session_id = f"klondike-{next(_SESSION_SEQ):05d}"
    sess = Session(session_id)
    sess.lang = lang
    if pipeline:
        sess.pipeline = list(pipeline)
    msg = Message("recognizer_loop:utterance", {"utterances": [utterance], "lang": lang},
                  {"session": sess.serialize(), "source": "klondike", "destination": "skills"})
    croft.bus.on("message", rec)
    hung = False
    asked = None  # None: no question; True: asked and released; False: asked, not released
    cut = None
    try:
        deadline = time.monotonic() + timeout
        # FakeBus.emit runs every handler in the emitting thread, so a stage
        # that never returns (a common-query provider whose can_answer
        # blocks; ovos-test-harness quarantines wolfie/wordnet for this)
        # would hang the whole run. The emit gets its own thread and a
        # deadline. While it runs, the loop below only plays the parts of a
        # device the test core lacks (end of speech, an answer to a
        # question); the verdict is still read after it returned or timed
        # out, so it does not depend on thread timing (the race
        # ovos-test-harness saw came from judging DURING emit).
        emitter = threading.Thread(target=croft.bus.emit, args=(msg,), daemon=True)
        emitter.start()
        spoken = 0
        while emitter.is_alive() and time.monotonic() < deadline:
            emitter.join(0.05)
            spoken = end_speech(croft, recs, session_id, spoken)
            if open_question(recs, session_id) is None:
                continue
            time.sleep(ASK_GRACE)
            enable = open_question(recs, session_id)
            if enable is None:
                continue
            # Everything after this point is the release, not the answer.
            cut = len(recs)
            asked = release_question(croft, enable, lang, recs, session_id)
            until = time.monotonic() + ASK_RELEASE
            while emitter.is_alive() and time.monotonic() < until:
                emitter.join(0.05)
                spoken = end_speech(croft, recs, session_id, spoken)
            break
        if emitter.is_alive():
            hung = True
        elif asked is None:
            while time.monotonic() < deadline:
                if any(m.msg_type in EOF_TYPES for m in list(recs) if _session_of(m) in ("", session_id)):
                    time.sleep(CAPTURE_SETTLE)
                    break
                time.sleep(0.05)
    finally:
        croft.bus.remove("message", rec)
    kept = list(recs)[:cut] if cut is not None else list(recs)
    return [m for m in kept if _session_of(m) in ("", session_id)], hung, asked


def open_question(recs, session_id):
    """The enable message of a question still waiting on this row's session."""
    pending = None
    for m in list(recs):
        if m.msg_type not in (ASK_ENABLE, ASK_DISABLE) or _session_of(m) != session_id:
            continue
        pending = m if m.msg_type == ASK_ENABLE else None
    return pending


def release_question(croft, enable, lang, recs, session_id):
    """Answer an open question with "cancel" in the asking session. True
    when the skill let go (disable seen) within ASK_RELEASE."""
    from ovos_bus_client.message import Message
    ctx = enable.context or {}
    cancel = Message("recognizer_loop:utterance", {"utterances": ["cancel"], "lang": lang},
                     {"session": ctx.get("session"), "source": "klondike", "destination": "skills"})
    threading.Thread(target=croft.bus.emit, args=(cancel,), daemon=True).start()
    until = time.monotonic() + ASK_RELEASE
    spoken = 0
    while time.monotonic() < until:
        if open_question(recs, session_id) is None:
            return True
        spoken = end_speech(croft, recs, session_id, spoken)
        time.sleep(0.05)
    return False


def end_speech(croft, recs, session_id, done):
    """Answer every new `speak` on the row's session with
    recognizer_loop:audio_output_end, as a device's audio service does when
    the sentence has been played. The test core has no audio service, so a
    skill that speaks with wait=True (get_response does, before it starts
    listening) would otherwise sit out the full 15 s speech timeout.
    Returns how many speaks have been answered."""
    speaks = [m for m in list(recs) if m.msg_type == "speak" and _session_of(m) == session_id]
    for m in speaks[done:]:
        try:
            croft.bus.emit(m.forward("recognizer_loop:audio_output_end"))
        except Exception as e:  # noqa: BLE001
            print(f"warning: audio_output_end not sent: {e}", file=sys.stderr)
    return len(speaks)


def claimant(recs, known_ids):
    """(skill_id or None, fired topics of that skill)."""
    types = {m.msg_type for m in recs}
    if "ovos.intent.unmatched" in types:
        return None, []
    who = None
    for m in recs:
        if ":" in m.msg_type and m.msg_type.split(":", 1)[0] in known_ids:
            who = m.msg_type.split(":", 1)[0]
            break
    if who is None:
        for m in recs:
            sid = (m.context or {}).get("skill_id")
            if sid in known_ids and m.msg_type == "speak":
                who = sid
                break
    if who is None:
        return None, []
    fired = [m.msg_type for m in recs if m.msg_type.startswith(f"{who}:")]
    fired += [str(m.data.get("name")) for m in recs if m.msg_type == "mycroft.skill.handler.start"
              and str(m.data.get("name", "")).startswith(f"{who}:")]
    return who, fired


def stage_of(recs):
    for m in reversed(recs):
        ctx = m.context or {}
        for key in ("pipeline", "pipeline_id", "matcher"):
            if key in ctx:
                return str(ctx[key])[:80]
    # No stage in any context: the last topic seen says where it stopped
    # (e.g. "question:query" for common query).
    for m in reversed(recs):
        if m.msg_type not in ("recognizer_loop:utterance",) and not m.msg_type.startswith("mycroft.skills."):
            return f"last message: {m.msg_type}"[:80]
    return None


def _bare(name):
    return name[:-len(".intent")] if name.endswith(".intent") else name


def label_forms(skill_id, expected):
    """Both spellings of the expected intent topic. ovos-workshop 1.x (stable)
    dispatches padatious intents as `skill:Name.intent`, current versions as
    `skill:Name`; a row may name it either way."""
    name = _bare(expected.split(":", 1)[1] if ":" in expected else expected)
    return {f"{skill_id}:{name}", f"{skill_id}:{name}.intent"}


def boot_route(ids, lang, pipeline, max_wait):
    """(croft, driver, pipeline actually on the row sessions, dropped stages)."""
    if modern_driver():
        import ovoscope
        keep, dropped = available_stages(pipeline)
        kwargs = {"lang": lang, "max_wait": max_wait}
        if keep:
            kwargs["default_pipeline"] = keep
        croft = ovoscope.get_minicroft(ids, **kwargs)
        # Drivers before ovoscope 1.x (testing resolves 0.13.1) emit
        # mycroft.skills.train at start but do not wait for the answer.
        # Ask and wait, as the legacy path does; a trained padatious
        # answers at once, so this costs nothing on newer drivers.
        import inspect
        if "wait_for_trained" not in inspect.signature(ovoscope.get_minicroft).parameters:
            if not legacy_train(croft, max_wait):
                dropped = dropped + ["(padatious did not confirm training)"]
        time.sleep(2.0)
        if keep:
            keep, more = warm_models(croft, keep)
            dropped += more
        return croft, f"ovoscope {getattr(ovoscope, '__version__', '') or 'modern'}", keep, dropped
    # Legacy driver (stable: ovoscope 0.6.0 on ovos-core 1.3). Its pipeline
    # ids predate the installer's plugin names, so the channel's own default
    # pipeline is used and published as such.
    croft, driver = boot(ids, [lang], max_wait, lambda _m: None)
    notes = []
    try:
        from ovos_config import Configuration
        used = list(Configuration().get("intents", {}).get("pipeline") or [])
        if used:
            notes.append(f"(channel default used: {len(used)} stages)")
    except Exception:  # noqa: BLE001
        pass
    # ovos-core 1.x padatious only trains when asked ("instant_train" is off
    # and the first train comes from the real SkillManager, which the
    # legacy MiniCroft replaces). Untrained, every padatious sentence falls
    # through to common query / fallback and reads as theft. Ask, and wait
    # for the answer the real core waits for.
    if not legacy_train(croft, max_wait):
        notes.append("(padatious did not confirm training)")
    return croft, driver, None, notes


def legacy_train(croft, max_wait):
    from ovos_bus_client.message import Message
    try:
        reply = croft.bus.wait_for_response(Message("mycroft.skills.train"),
                                            "mycroft.skills.trained", timeout=max_wait)
    except Exception as e:  # noqa: BLE001
        print(f"warning: training request failed: {e}", file=sys.stderr)
        return False
    return reply is not None


class BudgetReached(Exception):
    pass


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--manifest", required=True)
    ap.add_argument("--lang", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--max-wait", type=float, default=1800)
    # Common query alone searches for up to 6s before answering.
    ap.add_argument("--timeout", type=float, default=15.0, help="seconds per utterance")
    ap.add_argument("--budget", type=float, default=0,
                    help="seconds for this language, boot included (0: no limit); rows past it are "
                         "left out and the result is 'partial' (issue #15)")
    args = ap.parse_args()

    man = json.load(open(args.manifest))
    out = {"lang": args.lang, "status": "running", "results": {}}

    row_times = []

    def flush():
        if row_times:
            ts = sorted(row_times)
            out["row_seconds"] = {"n": len(ts), "median": round(ts[len(ts) // 2], 2),
                                  "p95": round(ts[min(len(ts) - 1, int(len(ts) * 0.95))], 2),
                                  "max": round(ts[-1], 2)}
        tmp = args.out + ".tmp"
        with open(tmp, "w") as f:
            json.dump(out, f, indent=1, default=str)
        os.replace(tmp, args.out)

    work = []  # (item, run, row)
    for item in man["items"]:
        for run, files in (item.get("runs") or {}).items():
            for path in files:
                for row in read_rows(path):
                    if same_language(row["lang"], args.lang):
                        work.append((item, run, row))
    shard_ids = sorted({sid for item in man["items"] for sid in item["skill_ids"]})
    started = time.monotonic()
    try:
        installed = installed_skill_ids()
        baseline_ids = sorted(installed - set(shard_ids) - set(man.get("exclude_ids") or []))
        out["baseline_ids"] = baseline_ids
        flush()
        croft, out["driver"], session_pipeline, out["pipeline_dropped"] = boot_route(
            baseline_ids + shard_ids, args.lang, man.get("pipeline") or [], args.max_wait)
    except BaseException as e:  # noqa: BLE001
        out.update(status="boot_failed", reason=f"{type(e).__name__}: {e}"[:500])
        traceback.print_exc()
        flush()
        os._exit(0)
    out["pipeline"] = session_pipeline
    out["boot_seconds"] = round(time.monotonic() - started, 1)
    loaded = {sid for sid, ld in (getattr(croft, "plugin_skills", {}) or {}).items()
              if getattr(ld, "instance", None) is not None}
    out["not_loaded"] = sorted(set(baseline_ids + shard_ids) - loaded)
    known = set(baseline_ids) | set(shard_ids)
    counted_ids = set(man.get("counted_ids") or [])
    uncounted_ids = set(man.get("uncounted_ids") or [])
    flush()

    try:
        for n, (item, run, row) in enumerate(work):
            if args.budget and time.monotonic() - started > args.budget:
                left = len(work) - n
                out["budget_skipped"] = left
                raise BudgetReached(f"routing budget reached; {left} rows not run")
            res = out["results"].setdefault(item["id"], {}).setdefault(run, {
                "hit": 0, "wrong_intent": 0, "baseline": 0, "unhandled": 0, "neighbour": 0,
                "hang": 0, "manual": 0, "not_loaded": 0, "total": 0, "asked": 0,
                "misses": [], "collisions": []})
            res["total"] += 1
            if row.get("needs_manual"):
                res["manual"] += 1
                continue
            own = row.get("skill_id") if row.get("skill_id") in item["skill_ids"] else item["skill_ids"][0]
            if own not in loaded:
                res["not_loaded"] += 1
                continue
            # A row in flight is recorded first: if the utterance hangs the
            # process, the outer runner finds it here and counts it as "hang".
            out["current"] = {"id": item["id"], "run": run, "utterance": row["utterance"][:200]}
            flush()
            t_row = time.monotonic()
            recs, hung, asked = capture(croft, row["utterance"], row["lang"], session_pipeline, args.timeout)
            row_times.append(time.monotonic() - t_row)
            who, fired = claimant(recs, known)
            expected = row.get("expected_intent", row.get("intent_label"))
            entry = {"utterance": row["utterance"][:200], "expected": expected, "taken_by": who}
            if asked is not None:
                # Whoever asked handled the sentence: the verdict below is
                # the usual one. `asked` counts the hits among them.
                entry["asked"] = True
                if asked is False:
                    out["questions_not_released"] = out.get("questions_not_released", 0) + 1
            if hung and who is None:
                # Nobody claimed it and a pipeline stage never returned: the
                # sentence got past every intent stage to one that blocks.
                res["hang"] += 1
                if len(res["misses"]) < MAX_MISSES:
                    res["misses"].append({**entry, "kind": "hang", "stage": stage_of(recs)})
                continue
            if who == own:
                if expected and not any(f in label_forms(own, expected) for f in fired):
                    res["wrong_intent"] += 1
                    entry["fired"] = sorted(set(fired))[:3]
                    entry["kind"] = "wrong_intent"
                else:
                    res["hit"] += 1
                    if asked is not None:
                        res["asked"] += 1
                    continue
            elif (who in shard_ids or who in uncounted_ids) and who not in counted_ids:
                res["neighbour"] += 1
                if len(res["collisions"]) < MAX_MISSES:
                    res["collisions"].append(entry)
                continue
            elif who is not None:
                res["baseline"] += 1
                entry["kind"] = "baseline"
                # Which stage matched says why (padatious, adapt, m2v, common
                # query ...): a skill winning through m2v only when many
                # more intents are loaded reads very differently.
                entry["stage"] = stage_of(recs)
            else:
                res["unhandled"] += 1
                entry["kind"] = "unhandled"
                entry["stage"] = stage_of(recs)
            if len(res["misses"]) < MAX_MISSES:
                res["misses"].append(entry)
        out.pop("current", None)
        out["status"] = "ok"
    except BudgetReached as e:
        out.pop("current", None)
        out.update(status="partial", reason=str(e))
    except BaseException as e:  # noqa: BLE001
        out.update(status="error", reason=f"{type(e).__name__}: {e}"[:500])
        traceback.print_exc()
    finally:
        out["seconds"] = round(time.monotonic() - started, 1)
        flush()
        try:
            croft.stop()
        except Exception:  # noqa: BLE001
            pass
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(0)


if __name__ == "__main__":
    main()
