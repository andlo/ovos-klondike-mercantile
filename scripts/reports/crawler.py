"""Crawler side of maintainer test reports (#6).

A maintainer commits the report their test tool wrote as
`test/reports/<channel>.json` in the skill's own repo. Each time the
crawler visits a Looks Complete entry it copies those files into
docs/reports/<entry id>/maintainer-<channel>.json, and removes the copy when
the file is gone from the repo. Nothing is judged here beyond "can we
publish this": whether it counts is re-derived on every crawl by
build_index, from the current release and channel.

A report that is malformed or carries private data is not copied. A stub
with the problems is stored instead, so the detail page can tell the
maintainer why their report does not show.
"""
import json
from datetime import datetime, timezone
from pathlib import Path

from reports.validate import CHANNELS, privacy_problems, structure_problems

REPORT_PATH = "test/reports/{channel}.json"
MAX_BYTES = 200_000


def sync_maintainer_reports(full_name, entry, fetch_file, reports_dir):
    """Returns {channel: "stored"|"invalid"|"removed"|None} for the log."""
    base = Path(reports_dir) / entry["id"]
    out = {}
    for channel in CHANNELS:
        repo_path = REPORT_PATH.format(channel=channel)
        dest = base / f"maintainer-{channel}.json"
        text = fetch_file(full_name, repo_path)
        if text is None:
            if dest.exists():
                dest.unlink()
                out[channel] = "removed"
            continue
        envelope = {"kind": "maintainer", "repo": full_name, "source": repo_path,
                    "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
        problems = []
        report = None
        if len(text.encode()) > MAX_BYTES:
            problems.append({"code": "too_large", "field": "", "message": "the report is larger than 200 kB"})
        else:
            try:
                report = json.loads(text)
            except ValueError as e:
                problems.append({"code": "json", "field": "", "message": f"not valid JSON ({str(e)[:120]})"})
        if report is not None:
            problems += structure_problems(report)
            if not problems:
                problems += privacy_problems(report)
            got = (report.get("manifest") or {}).get("channel") if not problems else None
            if not problems and got != channel:
                problems.append({"code": "wrong_channel", "field": "manifest.channel",
                                 "message": f"the file is named {channel}.json but the report is for {got}"})
        dest.parent.mkdir(parents=True, exist_ok=True)
        if problems:
            dest.write_text(json.dumps({"_klondike": {**envelope, "invalid": problems[:10]}}, indent=2) + "\n")
            out[channel] = "invalid"
        else:
            report = {k: v for k, v in report.items() if k != "_klondike"}
            report["_klondike"] = envelope
            dest.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
            out[channel] = "stored"
    return out
