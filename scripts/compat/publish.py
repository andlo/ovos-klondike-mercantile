#!/usr/bin/env python3
"""Merge test-shard artifacts into docs/, in the job that holds write access.

The artifacts were produced by a job that ran arbitrary PyPI code, so they
are treated as untrusted data:
  * a record is only accepted for an (id, channel) that plan.py put in THAT
    shard, with the key plan.py computed for it;
  * only known fields are kept, with type checks and length caps;
  * log excerpts are stored as plain text (the site renders them with
    textContent, never as HTML).

An "error" result (infra trouble) never replaces an earlier pass/fail; it is
kept beside it as last_error, and plan.py retries it on the next run.

Writes: docs/compat/results.json, docs/compat/stack-<channel>.txt and
docs/badges/<badge_id>/<channel>.json, and for the Klondike profile (#13)
docs/compat/klondike-profile-<channel>.txt and klondike-mycroft-<channel>.json.
Never the feed (see below).
"""
import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from compat.feed import (CHANNEL_ORDER, FINAL_STATUSES, LEVEL3_RATIO, SAFE_ID, badge_ids,  # noqa: E402
                         is_candidate, load_results, shields)

STR_FIELDS = {"id": 200, "channel": 20, "key": 32, "klondike_key": 32, "kind": 20, "package": 200,
              "requested_version": 64, "version_tested": 64, "tested_at": 40,
              "status": 12, "stage": 20, "reason": 600, "log_excerpt": 4000, "driver": 80, "languages_source": 10}
NUM_FIELDS = {"level", "duration_seconds", "boot_seconds"}
LIST_FIELDS = {"plugin_ids": 20, "languages_booted": 60, "languages_missing": 60,
               "warnings": 10, "stages": 20}


def clean(rec):
    out = {}
    for k, cap in STR_FIELDS.items():
        if isinstance(rec.get(k), str):
            out[k] = rec[k][:cap]
    for k in NUM_FIELDS:
        if isinstance(rec.get(k), (int, float)) and not isinstance(rec.get(k), bool):
            out[k] = rec[k]
    if isinstance(rec.get("channel_pinned"), bool):
        out["channel_pinned"] = rec["channel_pinned"]
    for k, cap in LIST_FIELDS.items():
        v = rec.get(k)
        if isinstance(v, list):
            out[k] = [str(x)[:200] for x in v[:cap]]
    regs = rec.get("registrations")
    if isinstance(regs, dict):
        out["registrations"] = {
            str(k)[:40]: (v if isinstance(v, int) else [str(x)[:120] for x in v[:20]])
            for k, v in list(regs.items())[:10] if isinstance(v, (int, list))}
    by_lang = rec.get("intents_by_lang")
    if isinstance(by_lang, dict):
        out["intents_by_lang"] = {str(k)[:20]: v for k, v in list(by_lang.items())[:60]
                                  if isinstance(v, int)}
    if out.get("status") not in FINAL_STATUSES + ("error",):
        return None
    # Level 3 is never taken from the artifact: it is capped at 2 here and
    # re-derived from the routing counts below.
    out["level"] = min(out.get("level", 0), 2) if out.get("level") in (0, 1, 2, 3) else 0
    if out["status"] == "pass":
        out["level"] = 2
    if isinstance(rec.get("klondike_key"), str) and out["status"] == "pass":
        # The Klondike line (#13) never changes the level or the badge.
        k = clean_routing(rec.get("klondike"))
        if k:
            out["klondike"] = k
    else:
        out.pop("klondike_key", None)
    if isinstance(rec.get("route_key"), str) and out["status"] == "pass":
        out["route_key"] = rec["route_key"][:32]
        routing = clean_routing(rec.get("routing"))
        if routing:
            out["routing"] = routing
            # Level 3 is re-derived here from the counts, never taken from
            # the artifact's own "level".
            if routing_level3(routing):
                out["level"] = 3
    return out


RUN_INTS = ("hit", "wrong_intent", "baseline", "unhandled", "neighbour", "hang", "manual",
            "not_loaded", "total", "counted", "asked")
MISS_STRS = {"utterance": 200, "expected": 200, "taken_by": 200, "kind": 20, "stage": 80, "lang": 20}


def _clean_miss(m):
    if not isinstance(m, dict):
        return None
    out = {k: m[k][:cap] for k, cap in MISS_STRS.items() if isinstance(m.get(k), str)}
    if isinstance(m.get("fired"), list):
        out["fired"] = [str(x)[:200] for x in m["fired"][:3]]
    if m.get("asked") is True:
        out["asked"] = True
    return out if out.get("utterance") else None


def _clean_run(r):
    if not isinstance(r, dict) or r.get("status") not in ("ok", "none", "unavailable", "error"):
        return None
    out = {"status": r["status"]}
    if isinstance(r.get("reason"), str):
        out["reason"] = r["reason"][:300]
    for k in RUN_INTS:
        if isinstance(r.get(k), int) and not isinstance(r.get(k), bool) and 0 <= r[k] < 100_000:
            out[k] = r[k]
    for k in ("langs", "langs_failed", "langs_not_routed", "langs_partial"):
        if isinstance(r.get(k), list):
            out[k] = [str(x)[:20] for x in r[k][:60]]
    for k, cap in (("misses", 25), ("collisions", 10)):
        if isinstance(r.get(k), list):
            out[k] = [c for c in (_clean_miss(m) for m in r[k][:cap]) if c]
    if out["status"] == "ok":
        counted, hit = out.get("counted", 0), out.get("hit")
        if not (counted > 0 and hit is not None) or hit > counted or counted > out.get("total", counted):
            return {"status": "none", "reason": "result counts were inconsistent and were not published"}
    return out


def clean_routing(routing):
    if not isinstance(routing, dict):
        return None
    out = {}
    for k, cap in (("ref", 100), ("install", 600), ("error", 300)):
        if isinstance(routing.get(k), str):
            out[k] = routing[k][:cap]
    for run in ("golden", "generated"):
        r = _clean_run(routing.get(run))
        if r:
            out[run] = r
    return out or None


def routing_level3(routing):
    g = (routing or {}).get("golden") or {}
    if g.get("status") != "ok" or g.get("hit", 0) > g.get("counted", 0):
        return False
    return g["hit"] / g["counted"] >= LEVEL3_RATIO


def _strs(v, n, cap):
    return [str(x)[:cap] for x in v[:n]] if isinstance(v, list) else []


def route_meta(meta, sdir, plan, docs, channel, now):
    """What level 3 ran against on this channel, from the first shard of this
    publish that routed: the installer baseline asked for, the skills that
    were actually loaded as baseline, the pipeline on the row sessions."""
    if (meta.get("route") or {}).get("run_at") == now:
        return
    try:
        route = json.loads((sdir / "route.json").read_text())
    except (OSError, ValueError):
        return
    if not isinstance(route, dict) or not isinstance(route.get("boots"), list):
        return
    boots = [b for b in route["boots"] if isinstance(b, dict)]
    first = next((b for b in boots if b.get("status") in ("ok", "partial")), boots[0] if boots else {})
    baseline = plan.get("baseline") or {}
    meta["route"] = {
        "run_at": now,
        "baseline_source": str(baseline.get("source", ""))[:200],
        "baseline_requirements": _strs(baseline.get("requirements"), 10, 200),
        "pipeline_requested": _strs(baseline.get("pipeline"), 30, 80),
        "pipeline_used": _strs(first.get("pipeline"), 30, 80),
        "pipeline_dropped": _strs(first.get("pipeline_dropped"), 30, 80),
        "baseline_ids": _strs(first.get("baseline_ids"), 80, 120),
        "excluded_ids": _strs(route.get("excluded_ids"), 20, 120),
        "driver": str(first.get("driver") or "")[:80],
        "generator_spec": str(plan.get("generator_spec") or "")[:200],
        "route_version": str(plan.get("route_version") or "")[:10],
        # How long routing took (issue #15), from the first shard that routed.
        "timing": [{"lang": str(b.get("lang", ""))[:20], "status": str(b.get("status", ""))[:20],
                    "seconds": b.get("seconds") if isinstance(b.get("seconds"), (int, float)) else None,
                    "row_seconds": {k: v for k, v in (b.get("row_seconds") if isinstance(b.get("row_seconds"), dict)
                                                      else {}).items()
                                    if k in ("n", "median", "p95", "max") and isinstance(v, (int, float))}}
                   for b in boots[:10]],
    }
    try:
        freeze = (sdir / "route-freeze.txt").read_text()[:200_000]
        (docs / "compat").mkdir(parents=True, exist_ok=True)
        (docs / "compat" / f"route-stack-{channel}.txt").write_text(freeze)
    except OSError:
        pass


def klondike_boots(out):
    boots = [b for b in (out or {}).get("boots") or [] if isinstance(b, dict)]
    return [{"lang": str(b.get("lang", ""))[:20], "status": str(b.get("status", ""))[:20],
             "seconds": b.get("seconds") if isinstance(b.get("seconds"), (int, float)) else None,
             "pipeline_used": _strs(b.get("pipeline"), 30, 80),
             "pipeline_dropped": _strs(b.get("pipeline_dropped"), 30, 80),
             "baseline_count": len(b["baseline_ids"]) if isinstance(b.get("baseline_ids"), list) else None}
            for b in boots[:10]]


def klondike_profile_meta(kmeta, spec, profile_def):
    """What the Klondike profile is on a channel, from the plan (trusted: it
    comes from the repo and the installer, not from a test job)."""
    curated = {c["id"]: c for c in (profile_def or {}).get("curated", {}).get("skills", [])
               + (profile_def or {}).get("curated", {}).get("pipeline", [])}
    kmeta["profile"] = {
        "requirements": list(spec["requirements"]),
        "pipeline": list(spec["pipeline"]),
        "added_stages": list(spec.get("added_stages") or []),
        "stages_not_added": dict(spec.get("stages_not_added") or {}),
        "curated": [{**curated[i], "in": i in spec["curated_members"]} for i in curated],
        "left_out": dict(spec.get("left_out") or {}),
        "extra_requirements": list((profile_def or {}).get("extra_requirements") or []),
        "sha256": spec["sha256"],
    }


def publish_profile_files(docs, channel, spec):
    """The profile as something a person can apply (issue #13): pip
    requirements to install under the channel's constraints, and the
    mycroft.conf pipeline that goes with them."""
    comp = docs / "compat"
    comp.mkdir(parents=True, exist_ok=True)
    head = [f"# Klondike profile, {channel} channel: a well-equipped OVOS install.",
            "# Install into the OVOS virtualenv under the channel's constraints:",
            f"#   pip install -c https://raw.githubusercontent.com/OpenVoiceOS/ovos-releases/main/"
            f"constraints-{channel}.txt -r klondike-profile-{channel}.txt",
            "# Then set the pipeline from klondike-mycroft-" + channel + ".json in mycroft.conf.", ""]
    (comp / f"klondike-profile-{channel}.txt").write_text("\n".join(head + list(spec["requirements"])) + "\n")
    (comp / f"klondike-mycroft-{channel}.json").write_text(
        json.dumps({"intents": {"pipeline": list(spec["pipeline"])}}, indent=2) + "\n")


def klondike_self_result(kmeta, sdir, spec, docs, channel, now):
    """The profile against itself, from the channel's klondike shard. Only
    ids the plan put in the profile's store map are accepted."""
    try:
        out = json.loads((sdir / "klondike.json").read_text())
    except (OSError, ValueError):
        out = None
    if not isinstance(out, dict):
        # Keep the last good result; a key of None makes plan.py retry.
        kmeta.setdefault("self", {})["last_error"] = {"run_at": now, "reason": "no result (the job did not finish)"}
        kmeta["key"] = None
        return
    allowed = {v["id"] for v in (spec.get("feed_map") or {}).values() if isinstance(v, dict)}
    if isinstance(out.get("error"), str):
        # The profile itself did not install (a pip resolution failure is a
        # finding in itself): shown as such, and retried next run.
        kmeta["self"] = {"run_at": now, "error": out["error"][:500]}
        kmeta["key"] = None
        return
    members = {}
    for mid, m in (out.get("members") or {}).items():
        if mid not in allowed or not isinstance(m, dict):
            continue
        members[mid] = {"version": str(m.get("version", ""))[:64], "skill_id": str(m.get("skill_id", ""))[:200],
                        "routing": clean_routing(m.get("routing"))}
    # Who takes whose sentences, both ways ("taken by X" / "takes from Y").
    by_skill = {m["skill_id"]: mid for mid, m in members.items()}
    takes_from = {}
    for mid, m in members.items():
        for run in ("golden", "generated"):
            for c in ((m.get("routing") or {}).get(run) or {}).get("collisions") or []:
                taker = by_skill.get(c.get("taken_by"))
                if taker:
                    takes_from.setdefault(taker, {}).setdefault(run, []).append(
                        {"from": mid, "utterance": c.get("utterance"), "lang": c.get("lang")})
    for taker, runs in takes_from.items():
        members[taker]["takes_from"] = {r: v[:10] for r, v in runs.items()}
    kmeta["self"] = {"run_at": now, "members": members,
                     "not_in_store": _strs(out.get("not_in_store"), 80, 200),
                     "langs": _strs(out.get("langs"), 10, 20),
                     "langs_skipped": _strs(out.get("langs_skipped"), 60, 20),
                     "boots": klondike_boots(out)}
    kmeta["key"] = spec.get("self_key")
    try:
        freeze = (sdir / "klondike-freeze.txt").read_text()[:200_000]
        (docs / "compat" / f"klondike-stack-{channel}.txt").write_text(freeze)
    except OSError:
        pass


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--plan", required=True, help="matrix JSON from plan.py")
    ap.add_argument("--artifacts", required=True, help="dir with shard-<channel>-<n>/ subdirs")
    ap.add_argument("--repo", default=".")
    args = ap.parse_args()

    repo = Path(args.repo)
    docs = repo / "docs"
    plan = json.loads(Path(args.plan).read_text())
    results_path = docs / "compat" / "results.json"
    doc = load_results(results_path)
    results = doc.setdefault("results", {})
    channels_meta = doc.setdefault("channels", {})
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")

    accepted = rejected = 0
    for shard in plan.get("include", []):
        channel, n = shard["channel"], shard["shard"]
        sdir = Path(args.artifacts) / f"shard-{channel}-{n}"
        expected = {i["id"]: i["key"] for i in shard["items"]}
        expected_route = {i["id"]: i.get("route_key") for i in shard["items"]}
        expected_klondike = {i["id"]: i.get("klondike_key") for i in shard["items"]}
        kmeta = doc.setdefault("klondike", {}).setdefault(channel, {})
        if n == "klondike":
            spec = {**json.loads(shard.get("klondike") or "{}"),
                    "self_key": ((plan.get("klondike") or {}).get(channel) or {}).get("self_key")}
            klondike_self_result(kmeta, sdir, spec, docs, channel, now)
            continue
        try:
            records = json.loads((sdir / "results.json").read_text())
        except (OSError, ValueError):
            print(f"warning: no results for {channel} shard {n}", file=sys.stderr)
            continue
        for raw in records if isinstance(records, list) else []:
            rec = clean(raw) if isinstance(raw, dict) else None
            if not rec or rec.get("channel") != channel or expected.get(rec.get("id")) != rec.get("key"):
                rejected += 1
                continue
            if rec.get("klondike_key") and rec["klondike_key"] != expected_klondike.get(rec["id"]):
                rec.pop("klondike_key", None)
                rec.pop("klondike", None)
            if rec.get("route_key") and rec["route_key"] != expected_route.get(rec["id"]):
                # Levels 1-2 stand; a level 3 result for another key does not.
                rec.pop("route_key", None)
                rec.pop("routing", None)
                rec["level"] = min(rec.get("level", 0), 2)
            per = results.setdefault(rec["id"], {})
            prev = per.get(channel)
            if rec["status"] == "error" and prev and prev.get("status") in FINAL_STATUSES:
                prev["last_error"] = {"tested_at": rec.get("tested_at"), "reason": rec.get("reason")}
            else:
                per[channel] = rec
            accepted += 1
        route_meta(channels_meta.setdefault(channel, {}), sdir, plan, docs, channel, now)
        if kmeta.get("route_run_at") != now:
            try:
                kroute = json.loads((sdir / "klondike-route.json").read_text())
                kmeta.update(route_run_at=now, route=klondike_boots(kroute))
            except (OSError, ValueError):
                pass
        # Channel metadata from the first shard that has it.
        meta = channels_meta.setdefault(channel, {})
        if meta.get("run_at") != now:
            try:
                stack = json.loads((sdir / "stack.json").read_text())
                meta["stack"] = {"python": str(stack.get("python", ""))[:20],
                                 "packages": {str(k)[:60]: (str(v)[:40] if v else None)
                                              for k, v in list(stack.get("packages", {}).items())[:20]}}
                freeze = (sdir / "stack-freeze.txt").read_text()[:200_000]
                (docs / "compat").mkdir(parents=True, exist_ok=True)
                (docs / "compat" / f"stack-{channel}.txt").write_text(freeze)
                meta.update(run_at=now,
                            constraints_sha256=plan["summary"][channel]["constraints_sha256"],
                            constraints_url=f"https://raw.githubusercontent.com/OpenVoiceOS/ovos-releases/main/constraints-{channel}.txt",
                            harness_sha=plan.get("harness_sha"),
                            runner_version=plan.get("runner_version"))
            except (OSError, ValueError, KeyError):
                pass
    for channel, spec in (plan.get("klondike") or {}).items():
        kmeta = doc.setdefault("klondike", {}).setdefault(channel, {})
        klondike_profile_meta(kmeta, spec, plan.get("klondike_profile"))
        # The skill ids a device must have for a report to count as a
        # Klondike-test report: what the profile installed in the last run
        # that routed it against itself, plus the curated skills' own ids.
        self_ = kmeta.get("self") or {}
        ids = {m["skill_id"] for m in (self_.get("members") or {}).values() if m.get("skill_id")}
        ids |= set(self_.get("not_in_store") or [])
        for cid in spec.get("curated_members") or []:
            rec = (doc["results"].get(cid) or {}).get(channel) or {}
            if rec.get("kind") == "skill":
                ids |= set(rec.get("plugin_ids") or [])
        kmeta["profile"]["skill_ids"] = sorted(ids)
        added = set(kmeta["profile"]["added_stages"])
        kmeta["profile"]["stage_rules"] = [
            {k: c[k] for k in ("stage", "after", "before") if k in c}
            for c in ((plan.get("klondike_profile") or {}).get("curated") or {}).get("pipeline", [])
            if c.get("stage") in added]
        publish_profile_files(docs, channel, spec)
    doc["generated_at"] = now
    print(f"accepted {accepted} records, rejected {rejected}")

    # The feed is read, never written: the crawler owns docs/skills.json and
    # skills/*.json and re-attaches the compat field from results.json on
    # every run. Writing it here too would make the crawler's push-rebase
    # conflict on skills.json and lose a whole crawl.
    feed_path = docs / "skills.json"
    entries = json.loads(feed_path.read_text())
    valid = {e["id"] for e in entries}
    doc["results"] = {k: v for k, v in results.items() if k in valid}
    results_path.parent.mkdir(parents=True, exist_ok=True)
    results_path.write_text(json.dumps(doc, indent=2, sort_keys=True) + "\n")

    # Badges: one endpoint per candidate and channel (untested ones too, so
    # a README badge works from the day the skill becomes Looks Complete).
    # Same badge ids as the crawler's compat field (feed.badge_ids).
    candidates = [e for e in entries if is_candidate(e)]
    ids = badge_ids([(e, doc["results"].get(e["id"])) for e in candidates])
    channels = [c for c in CHANNEL_ORDER if c in plan.get("summary", {}) or c in channels_meta]
    badges = docs / "badges"
    for e in candidates:
        bid = ids[e["id"]]
        if not SAFE_ID.match(bid):
            continue
        for channel in channels:
            rec = doc["results"].get(e["id"], {}).get(channel)
            out = badges / bid / f"{channel}.json"
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(json.dumps(shields(channel, rec)) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
