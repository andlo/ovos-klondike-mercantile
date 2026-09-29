"""Test reports from people, next to Klondike's own channel tests.

  maintainer  a skill's maintainer tested on their own device and committed
              the report to the skill's repo (#6): `test/reports/<channel>.json`,
              picked up by the crawler.
  community   anyone submitted a report from their own setup through the
              detail page / issue form (#9), stored by process-test-report.yml.

Stored under docs/reports/<entry id>/:
  maintainer-<channel>.json
  community/<channel>/<github user>-<skill version>.json

Every stored report keeps what the submitter sent plus a small `_klondike`
envelope (who, when, from where). Its status (current / stale) is NOT
stored: it is re-derived on every crawl and every submission from the
current release, the channel's current constraints and the stack the
channel installs today (validate.check), so a report goes stale without
anyone touching it. docs/reports/index.json is the summary pages read.
"""
import json
import math
from pathlib import Path

from reports.validate import CHANNELS, check

INDEX_VERSION = 1
MAX_HISTORY = 20


def summarize_entry(entry, stored, constraints, channel_stacks, latest=None):
    """{channel: {"maintainer": {...}|None, "community": {...}}} for one entry.

    `stored` is {"maintainer": {channel: report}, "community": {channel: [report, ...]}}.
    `latest` is the current release as PyPI says it now; the feed's
    pypi_version is only a fallback, since the crawler refreshes an entry
    only when its rotation slot comes up (plan.py asks PyPI for the same
    reason)."""
    latest = latest or entry.get("pypi_version")
    out = {}
    for channel in CHANNELS:
        m = (stored.get("maintainer") or {}).get(channel)
        community = (stored.get("community") or {}).get(channel) or []
        if not m and not community:
            continue
        row = {"maintainer": None, "community": None}
        stub = (m or {}).get("_klondike", {}).get("invalid") if m else None
        if stub:
            env = m["_klondike"]
            row["maintainer"] = {"status": "invalid", "passes": False, "source": env.get("source"),
                                 "problems": [p["message"] for p in stub][:5]}
            m = None
        if m:
            res = check(m, entry.get("package_name"), latest, constraints.get(channel), channel_stacks.get(channel))
            row["maintainer"] = {
                "status": res["status"], "passes": res["passes"],
                "level": m.get("level"), "version": m["skill"]["version"],
                "created_at": m.get("created_at"), "tool": m.get("tool"),
                "setup": (m.get("setup") or {}).get("notes") or "",
                "utterances": m.get("utterances"),
                "problems": [p["message"] for p in res["problems"]][:5],
                "source": (m.get("_klondike") or {}).get("source"),
            }
        if community:
            counts = {"works": 0, "partly": 0, "doesnt_work": 0}
            reports, history = [], 0
            for r in community:
                res = check(r, entry.get("package_name"), latest, constraints.get(channel), channel_stacks.get(channel))
                if res["status"] == "invalid":
                    continue
                current = res["status"] == "current"
                outcome = r.get("outcome") or ("works" if res["passes"] else "doesnt_work")
                if current:
                    counts[outcome] += 1
                else:
                    history += 1
                setup = r.get("setup") or {}
                reports.append({
                    "user": (r.get("_klondike") or {}).get("user"),
                    "current": current, "outcome": outcome, "version": r["skill"]["version"],
                    "created_at": r.get("created_at"),
                    "hardware": setup.get("hardware") or "", "languages": setup.get("languages") or [],
                    "stt": setup.get("stt") or "", "tts": setup.get("tts") or "",
                    "notes": setup.get("notes") or "",
                    "stale_reason": "" if current else (res["problems"][0]["message"] if res["problems"] else ""),
                })
            reports.sort(key=lambda x: x.get("created_at") or "", reverse=True)
            row["community"] = {**counts, "history": history,
                                "reports": [x for x in reports if x["current"]]
                                + [x for x in reports if not x["current"]][:MAX_HISTORY]}
        out[channel] = row
    return out


def load_stored(reports_dir, entry_id):
    base = Path(reports_dir) / entry_id
    stored = {"maintainer": {}, "community": {}}
    if not base.is_dir():
        return stored
    for channel in CHANNELS:
        path = base / f"maintainer-{channel}.json"
        if path.is_file():
            try:
                stored["maintainer"][channel] = json.loads(path.read_text())
            except ValueError:
                pass
        cdir = base / "community" / channel
        if cdir.is_dir():
            items = []
            for p in sorted(cdir.glob("*.json")):
                try:
                    items.append(json.loads(p.read_text()))
                except ValueError:
                    pass
            stored["community"][channel] = items
    return stored


def build_index(entries, reports_dir, constraints, channel_stacks, latest_release=None):
    """Re-derive every stored report's status; returns the index document.
    `latest_release(package)` returns the current release (or None)."""
    index = {"version": INDEX_VERSION, "entries": {}}
    for entry in entries:
        stored = load_stored(reports_dir, entry["id"])
        if not stored["maintainer"] and not stored["community"]:
            continue
        latest = latest_release(entry.get("package_name")) if latest_release and entry.get("package_name") else None
        summary = summarize_entry(entry, stored, constraints, channel_stacks, latest)
        if summary:
            index["entries"][entry["id"]] = summary
    return index


def compact(summary):
    """What cards, filters and the sort need, per channel."""
    out = {}
    for channel, row in (summary or {}).items():
        m = row.get("maintainer")
        c = row.get("community") or {}
        state = None
        if m and m["status"] == "current":
            state = "pass" if m["passes"] else "fail"
        elif m:
            state = m["status"]  # stale or invalid: shown on the detail page, never counted
        out[channel] = {
            "maintainer": state,
            "maintainer_level": m.get("level") if m else None,
            "works": c.get("works", 0), "partly": c.get("partly", 0), "doesnt_work": c.get("doesnt_work", 0),
        }
    return out


def attach_reports(entries, index):
    """Set/refresh entry["reports"] from the index; drop it where there is none."""
    by_id = (index or {}).get("entries", {})
    for e in entries:
        if e["id"] in by_id:
            e["reports"] = compact(by_id[e["id"]])
        else:
            e.pop("reports", None)
    return entries


def community_weight(works, doesnt_work):
    """Diminishing returns (#9): a handful of confirmations helps, fifty do not
    outweigh our own tests or a maintainer report. Bounded to +-0.45 so it
    moves a skill within its band, never into the next one. Same formula as
    communityWeight() in docs/shared.js."""
    return max(-0.45, min(0.45, 0.3 * math.log10(1 + works) - 0.3 * math.log10(1 + doesnt_work)))
