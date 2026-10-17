"""Shared by the crawler and the compat publish job: turn compat results into
the compact `compat` field on each feed entry, and the shields.io badges.

docs/compat/results.json is the single source of truth. The feed only
carries what cards and filters need; the detail page loads results.json for
the full record (log excerpt, registrations, per-language counts).
"""
import json
import re
from pathlib import Path

PAGES_URL = "https://andlo.github.io/ovos-klondike-mercantile"
CHANNEL_ORDER = ["stable", "testing", "alpha"]
# Feed component_type -> probe kind. Other plugin types (TTS, STT, wake
# word ...) need hardware or models and are not meaningful in MiniCroft.
TESTED_TYPES = {"Skill": "skill", "Pipeline Plugin": "pipeline"}


# Results that are final for their key (not retried). pass/fail are the
# package's own result; the grey ones say it could not be judged here, for a
# stated reason, and are never shown as a failure.
FINAL_STATUSES = ("pass", "fail", "unsupported", "needs_device", "needs_config")
GREY_LABELS = {"unsupported": "not supported", "needs_device": "needs device",
               "needs_config": "needs config"}

# Level 3 is reached when at least this share of a skill's counted golden
# rows reach it with the installer's default skills loaded. Labels always
# show the exact numbers.
LEVEL3_RATIO = 0.8

# Generated utterances (ovoscope generate, OpenVoiceOS/ovoscope#224) are run
# and stored in results.json, but not shown on cards, badges or in the feed
# until #224 is merged or settled upstream. Flip this, and the same switch
# in docs/shared.js, to publish them.
PUBLIC_GENERATED = False


LEVEL3_LANG = "en-US"


def level3_counts(r):
    """(hit, counted) that decides level 3 for one routing run, else None.

    The en-US rows (#67): which other languages a run routes depends on the
    shard and the routing budget, not on the skill, so they are reported as
    language coverage and don't decide the level. A result from before the
    per-language counts (no by_lang) falls back to its totals."""
    if not isinstance(r, dict) or r.get("status") != "ok" or not r.get("counted"):
        return None
    by = r.get("by_lang")
    if isinstance(by, dict):
        c = by.get(LEVEL3_LANG)
        if not isinstance(c, dict) or not c.get("counted"):
            return None
        return c.get("hit", 0), c["counted"]
    return r.get("hit", 0), r["counted"]


def routing_counts(rec, run):
    """(hit, counted) of a finished routing run that decides level 3, else None."""
    return level3_counts(((rec or {}).get("routing") or {}).get(run))


# A fallback of last resort (#75), the rule of ovos-tui-client 0.3.0a14
# (andlo/ovos-tui-client#80): fallback-unknown ("I don't know") answers what
# nothing else takes, so on a real install its golden utterances reach other
# skills and stages first, as they should, and can't measure it. Measured,
# not named: a skill whose fallback is in OVOS's low band (priority above
# 90: ovos-fallback-pipeline-plugin-low, after everything else) and whose
# en-US golden utterances went to another skill or stage at least half the
# time. A high or medium fallback (application-launcher, priority 4) is not
# a last resort: what takes its sentences is shown as usual. One that is
# broken (its handler fails, or it says nothing) isn't marked either: there
# the misses point at the skill itself.
LAST_RESORT_ABOVE = 90
LAST_RESORT_LABEL = "✓ loads · last-resort fallback"
LAST_RESORT_NOTE = ("a fallback of last resort: its golden utterances reach other skills and stages "
                    "first, as they should, so they don't measure it; graded by level 2")


def taken_counts(r):
    """(taken by another skill or stage, counted) of the en-US rows of one
    routing run, else None (also for a result from before `taken` was counted)."""
    if not isinstance(r, dict) or r.get("status") != "ok" or not r.get("counted"):
        return None
    by = r.get("by_lang")
    c = by.get(LEVEL3_LANG) if isinstance(by, dict) else r
    if not isinstance(c, dict) or not c.get("counted") or not isinstance(c.get("taken"), int):
        return None
    return c["taken"], c["counted"]


def last_resort(rec):
    """Is this result a fallback of last resort (#75)?"""
    if not rec or rec.get("status") != "pass" or rec.get("kind", "skill") != "skill":
        return False
    prio = rec.get("fallback_priority")
    if not isinstance(prio, int) or isinstance(prio, bool) or prio <= LAST_RESORT_ABOVE:
        return False
    c = taken_counts(((rec.get("routing") or {}).get("golden")))
    return bool(c and c[0] * 2 >= c[1])


def is_candidate(entry):
    """Looks Complete (tier 1), a tested type, not archived, has a package."""
    return (entry.get("tier") == 1 and entry.get("component_type") in TESTED_TYPES
            and not entry.get("archived") and bool(entry.get("package_name")))


def load_results(path):
    path = Path(path)
    if not path.exists():
        return {"channels": {}, "results": {}}
    return json.loads(path.read_text())


def stop_result(rec):
    """The stop check (#16) when it means something: stops / keeps_going / stuck."""
    r = ((rec or {}).get("routing") or {}).get("stop") or {}
    return r.get("result") if r.get("result") in ("stops", "keeps_going", "stuck") else None


def label(rec):
    """(short text, state) for one result; state is pass/warn/fail/untested."""
    if rec and rec.get("status") in GREY_LABELS:
        return GREY_LABELS[rec["status"]], "unsupported"
    if not rec or rec.get("status") not in ("pass", "fail"):
        return "untested", "untested"
    if rec["status"] == "fail":
        return ("✗ doesn't install", "fail") if rec.get("level", 0) == 0 else ("✗ doesn't load", "fail")
    booted = rec.get("languages_booted") or []
    missing = rec.get("languages_missing") or []
    if last_resort(rec):
        return LAST_RESORT_LABEL, "warn" if rec.get("warnings") else "pass"
    golden = routing_counts(rec, "golden")
    stop = stop_result(rec)
    if golden:
        hit, counted = golden
        if hit / counted < LEVEL3_RATIO:
            return f"✓ loads · {hit}/{counted} golden", "warn"
        clean = hit == counted and not missing and not rec.get("warnings")
        if stop == "stops":
            return f"✓ {hit}/{counted} golden · stops", "pass" if clean else "warn"
        if stop in ("keeps_going", "stuck"):
            return f"✓ {hit}/{counted} golden · doesn't stop", "warn"
        return f"✓ {hit}/{counted} golden", "pass" if clean else "warn"
    if missing and booted:
        return f"✓ loads · {len(booted) - len(missing)}/{len(booted)} langs", "warn"
    if rec.get("warnings"):
        return "✓ loads", "warn"
    return "✓ loads", "pass"


def compact(rec):
    text, state = label(rec)
    out = {"label": text, "state": state, "level": rec.get("level", 0)}
    if stop_result(rec):
        out["stop"] = stop_result(rec)
    for k in ("version_tested", "tested_at", "channel_pinned"):
        if rec.get(k) is not None:
            out[k] = rec[k]
    if last_resort(rec):
        # graded by level 2: no golden counts on the card (#75)
        out["last_resort"] = True
        return out
    runs = ("golden", "generated") if PUBLIC_GENERATED else ("golden",)
    for run in runs:
        counts = routing_counts(rec, run)
        if counts:
            out[run] = {"hit": counts[0], "counted": counts[1]}
    return out


SAFE_ID = re.compile(r"^[A-Za-z0-9._-]{1,200}$")


def badge_ids(entries):
    """entry id -> badge id for every candidate entry: the skill's own id
    (from its entry point once installed, else skill.json), unless two
    candidates would share it, in which case both use their entry id.
    Always URL-path safe: some skill.json skill_ids are a whole entry-point
    string ("skill-about.neongeckocom=skill_about:AboutSkill")."""
    wanted = {}
    for entry, per_channel in entries:
        plugin_ids = []
        for rec in (per_channel or {}).values():
            plugin_ids = plugin_ids or rec.get("plugin_ids") or []
        candidate = (plugin_ids[0] if plugin_ids else None) or entry.get("skill_id") or entry["id"]
        candidate = candidate.split("=", 1)[0].strip()
        wanted[entry["id"]] = candidate if SAFE_ID.match(candidate) else entry["id"]
    counts = {}
    for b in wanted.values():
        counts[b] = counts.get(b, 0) + 1
    return {eid: (b if counts[b] == 1 else eid) for eid, b in wanted.items()}


def attach_compat(entries, results_doc):
    """Set/refresh entry["compat"] in place on every candidate (untested ones
    get an empty channel map, so the detail page can offer the badge
    snippet from day one); drop it from everything else."""
    results = results_doc.get("results", {})
    candidates = [e for e in entries if is_candidate(e)]
    ids = badge_ids([(e, results.get(e["id"])) for e in candidates])
    for e in entries:
        if e["id"] not in ids:
            e.pop("compat", None)
            continue
        per_channel = results.get(e["id"]) or {}
        channels = {c: compact(per_channel[c]) for c in CHANNEL_ORDER if c in per_channel}
        e["compat"] = {"badge_id": ids[e["id"]], "channels": channels}
    return entries


def shields(channel, rec):
    text, state = label(rec)
    color = {"pass": "brightgreen", "warn": "yellowgreen", "fail": "red"}.get(state, "lightgrey")
    return {"schemaVersion": 1, "label": f"ovos {channel}", "message": text,
            "color": color, "cacheSeconds": 3600}


def badge_url(badge_id, channel):
    return (f"https://img.shields.io/endpoint?url={PAGES_URL}/badges/{badge_id}/{channel}.json")
