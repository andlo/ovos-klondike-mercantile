#!/usr/bin/env python3
"""Store one submitted test report (issue #9) from a "Test report:" issue.

Everything about the issue is untrusted input: the body, the title and the
report inside it. It is read from environment variables (never templated
into a shell), parsed as data, checked with the same rules the detail page
applied (validate.check), and stored only when it passes. Nothing in it is
ever executed or rendered as HTML.

Env: ISSUE_TITLE, ISSUE_BODY, ISSUE_USER, ISSUE_NUMBER, USER_CREATED_AT
(ISO date of the GitHub account), IS_MAINTAINER ("true" when the user owns
the skill's repo or is a public member of its org).
Writes the outcome as JSON to --out: {"verdict", "message", "path"?}.
"""
import argparse
import json
import os
import re
import sys
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from reports.validate import CHANNELS, check  # noqa: E402

MIN_ACCOUNT_AGE = timedelta(days=30)
MAX_REPORT_BYTES = 200_000
# The constraints the OVOS installer uses, as the channel tests do (plan.py).
CONSTRAINTS_URL = "https://raw.githubusercontent.com/OpenVoiceOS/ovos-releases/main/constraints-{channel}.txt"
SAFE = re.compile(r"^[A-Za-z0-9._-]{1,200}$")


def section(body, label):
    """The value of one issue-form field ("### Label\n\nvalue")."""
    m = re.search(rf"^###\s+{re.escape(label)}\s*$(.*?)(?=^###\s|\Z)", body or "", re.M | re.S)
    return m.group(1).strip() if m else ""


def report_json(text):
    m = re.search(r"```(?:json)?\s*\n(.*?)\n```", text, re.S)
    raw = (m.group(1) if m else text).strip()
    if len(raw.encode()) > MAX_REPORT_BYTES:
        raise ValueError("the report is larger than 200 kB")
    return json.loads(raw)


def fetch(url):
    req = urllib.request.Request(url, headers={"User-Agent": "ovos-klondike-mercantile reports"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read().decode()


def latest_release(package):
    try:
        return json.loads(fetch(f"https://pypi.org/pypi/{package}/json"))["info"]["version"]
    except Exception:  # noqa: BLE001 - fall back to the feed's copy
        return None


def channel_stacks(docs):
    try:
        channels = json.loads((docs / "compat" / "results.json").read_text()).get("channels", {})
    except (OSError, ValueError):
        return {}
    return {c: (m.get("stack") or {}).get("packages") or {} for c, m in channels.items()}


def process(env, docs, now=None, fetch_text=None, latest=None):
    """Returns (outcome dict, report to store or None, relative store path or None).
    `fetch_text(url)` and `latest(package)` default to the network; tests
    pass their own."""
    now = now or datetime.now(timezone.utc)
    fetch_text = fetch_text or fetch
    latest = latest or latest_release
    user = env.get("ISSUE_USER", "")
    if not SAFE.match(user):
        return {"verdict": "invalid", "message": "Couldn't read the GitHub user."}, None, None
    body = env.get("ISSUE_BODY", "")
    entry_id = section(body, "Entry") or re.sub(r"^Test report:\s*", "", env.get("ISSUE_TITLE", "")).strip()
    entry_id = entry_id.strip("` ")
    feed = {e["id"]: e for e in json.loads((docs / "skills.json").read_text())}
    entry = feed.get(entry_id) if SAFE.match(entry_id or "") else None
    if entry is None:
        return {"verdict": "invalid", "message": f"There is no Klondike entry `{entry_id[:100]}`. "
                "Use the id from the detail page address (`detail.html?id=...`)."}, None, None
    try:
        report = report_json(section(body, "Report"))
    except ValueError as e:
        return {"verdict": "invalid", "message": f"The report is not valid JSON ({str(e)[:200]})."}, None, None

    channel = report.get("channel") if isinstance(report, dict) else None
    constraints = None
    if channel in CHANNELS:
        try:
            constraints = fetch_text(CONSTRAINTS_URL.format(channel=channel))
        except Exception:  # noqa: BLE001
            constraints = None
    current = latest(entry.get("package_name") or "") or entry.get("pypi_version")
    res = check(report, entry.get("package_name"), current, constraints, channel_stacks(docs).get(channel))
    if res["status"] == "invalid":
        lines = "\n".join(f"- `{p['field'] or 'report'}`: {p['message']}" for p in res["problems"][:10])
        return {"verdict": "invalid", "message": "The report was not stored:\n\n" + lines}, None, None
    if res["status"] == "stale":
        lines = "\n".join(f"- {p['message']}" for p in res["problems"][:5])
        return {"verdict": "stale", "message": "The report is well-formed but would only count as history, "
                "so it was not stored:\n\n" + lines + "\n\nRe-run the test on the current release and "
                "channel and submit again."}, None, None

    if env.get("IS_MAINTAINER") == "true":
        return {"verdict": "maintainer", "message": (
            "You maintain this skill, so your report counts as a maintainer report. Those live in the "
            "skill's own repo: commit it as `test/reports/" + channel + ".json` and Klondike picks it up "
            "on its next visit (within about a day). See *Test your skill on a real device* on the "
            "For maintainers page.")}, None, None
    try:
        created = datetime.fromisoformat(env.get("USER_CREATED_AT", "").replace("Z", "+00:00"))
    except ValueError:
        created = now
    if now - created < MIN_ACCOUNT_AGE:
        return {"verdict": "young_account", "message": (
            "Reports are counted from GitHub accounts at least 30 days old, to keep the counts honest. "
            "Please submit it again later.")}, None, None

    report = {k: v for k, v in report.items() if k != "_klondike"}
    report["_klondike"] = {"user": user, "issue": int(env.get("ISSUE_NUMBER") or 0),
                           "received_at": now.isoformat(timespec="seconds"), "kind": "community"}
    version = re.sub(r"[^A-Za-z0-9._-]", "_", report["skill"]["version"])[:64]
    rel = Path("reports") / entry_id / "community" / channel / f"{user}-{version}.json"
    replaced = (docs / rel).exists()
    outcome = report.get("outcome") or ("works" if res["passes"] else "doesnt_work")
    label = {"works": "works", "partly": "works partly", "doesnt_work": "doesn't work"}[outcome]
    hw = (report.get("setup") or {}).get("hardware") or "your setup"
    return {"verdict": "stored", "path": str(rel), "message": (
        f"Thanks! Stored as a community report for **{channel}**: {label} on {hw}"
        f"{' (it replaces your earlier report for this version)' if replaced else ''}. "
        f"It shows on the detail page once the site has been rebuilt, usually within a few minutes.")}, report, rel


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--docs", default="docs")
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    docs = Path(args.docs)
    outcome, report, rel = process(os.environ, docs)
    if report is not None:
        path = docs / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    Path(args.out).write_text(json.dumps(outcome))
    print(outcome["verdict"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
