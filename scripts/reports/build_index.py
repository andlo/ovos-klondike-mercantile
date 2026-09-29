#!/usr/bin/env python3
"""Rebuild docs/reports/index.json from every stored report.

Run by the crawler after each crawl and by process-test-report.yml after a
submission. Statuses are derived here, from the current release, each
channel's constraints (fetched live) and the stack the channel installs
today (docs/compat/results.json), so reports go stale on their own.
"""
import argparse
import json
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from reports.feed import build_index  # noqa: E402
from reports.validate import CHANNELS  # noqa: E402

# The constraints the OVOS installer uses, as the channel tests do (plan.py).
CONSTRAINTS_URL = "https://raw.githubusercontent.com/OpenVoiceOS/ovos-releases/main/constraints-{channel}.txt"


def fetch_constraints():
    out = {}
    for channel in CHANNELS:
        try:
            req = urllib.request.Request(CONSTRAINTS_URL.format(channel=channel),
                                         headers={"User-Agent": "ovos-klondike-mercantile reports"})
            with urllib.request.urlopen(req, timeout=30) as r:
                out[channel] = r.read().decode()
        except Exception:  # noqa: BLE001 - that channel's reports read as "constraints unavailable"
            out[channel] = None
    return out


def latest_release(package):
    try:
        req = urllib.request.Request(f"https://pypi.org/pypi/{package}/json",
                                     headers={"User-Agent": "ovos-klondike-mercantile reports"})
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read())["info"]["version"]
    except Exception:  # noqa: BLE001 - the feed's pypi_version is the fallback
        return None


def channel_stacks(docs):
    try:
        channels = json.loads((docs / "compat" / "results.json").read_text()).get("channels", {})
    except (OSError, ValueError):
        return {}
    return {c: (m.get("stack") or {}).get("packages") or {} for c, m in channels.items()}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--docs", default="docs")
    args = ap.parse_args()
    docs = Path(args.docs)
    entries = json.loads((docs / "skills.json").read_text())
    index = build_index(entries, docs / "reports", fetch_constraints(), channel_stacks(docs),
                        latest_release)
    (docs / "reports").mkdir(parents=True, exist_ok=True)
    (docs / "reports" / "index.json").write_text(json.dumps(index, indent=1, sort_keys=True) + "\n")
    print(f"reports index: {len(index['entries'])} entries with reports")
    return 0


if __name__ == "__main__":
    sys.exit(main())
