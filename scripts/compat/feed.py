"""Shared by the crawler and the compat publish job: turn compat results into
the compact `compat` field on each feed entry, and the shields.io badges.

docs/compat/results.json is the single source of truth. The feed only
carries what cards and filters need; the detail page loads results.json for
the full record (log excerpt, registrations, per-language counts).
"""
import json
from pathlib import Path

PAGES_URL = "https://andlo.github.io/ovos-klondike-mercantile"
CHANNEL_ORDER = ["stable", "testing", "alpha"]
# Feed component_type -> probe kind. Other plugin types (TTS, STT, wake
# word ...) need hardware or models and are not meaningful in MiniCroft.
TESTED_TYPES = {"Skill": "skill", "Pipeline Plugin": "pipeline"}


def is_candidate(entry):
    """Looks Complete (tier 1), a tested type, not archived, has a package."""
    return (entry.get("tier") == 1 and entry.get("component_type") in TESTED_TYPES
            and not entry.get("archived") and bool(entry.get("package_name")))


def load_results(path):
    path = Path(path)
    if not path.exists():
        return {"channels": {}, "results": {}}
    return json.loads(path.read_text())


def label(rec):
    """(short text, state) for one result; state is pass/warn/fail/untested."""
    if rec and rec.get("status") == "unsupported":
        return "not supported", "unsupported"
    if not rec or rec.get("status") not in ("pass", "fail"):
        return "untested", "untested"
    if rec["status"] == "fail":
        return ("✗ doesn't install", "fail") if rec.get("level", 0) == 0 else ("✗ doesn't load", "fail")
    booted = rec.get("languages_booted") or []
    missing = rec.get("languages_missing") or []
    if missing and booted:
        return f"✓ loads · {len(booted) - len(missing)}/{len(booted)} langs", "warn"
    if rec.get("warnings"):
        return "✓ loads", "warn"
    return "✓ loads", "pass"


def compact(rec):
    text, state = label(rec)
    out = {"label": text, "state": state, "level": rec.get("level", 0)}
    for k in ("version_tested", "tested_at", "channel_pinned"):
        if rec.get(k) is not None:
            out[k] = rec[k]
    return out


def badge_ids(entries):
    """entry id -> badge id for every candidate entry: the skill's own id
    (from its entry point once installed, else skill.json), unless two
    candidates would share it, in which case both use their entry id."""
    wanted = {}
    for entry, per_channel in entries:
        plugin_ids = []
        for rec in (per_channel or {}).values():
            plugin_ids = plugin_ids or rec.get("plugin_ids") or []
        wanted[entry["id"]] = (plugin_ids[0] if plugin_ids else None) or entry.get("skill_id") or entry["id"]
    counts = {}
    for b in wanted.values():
        counts[b] = counts.get(b, 0) + 1
    return {eid: (b if counts[b] == 1 and "/" not in b else eid) for eid, b in wanted.items()}


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
