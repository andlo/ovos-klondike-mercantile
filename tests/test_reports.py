#!/usr/bin/env python3
"""Checks for the test-report pieces (#6 maintainer, #9 community reports).

Run: python3 tests/test_reports.py   (needs `packaging` and `node`)

1. validate.check on hand-made cases (status, passes, problem codes)
2. parity: docs/reports.js gives the same answers on the same cases, and
   its PEP 440 subset agrees with `packaging` on every pin of both real
   constraints files
3. a submission end to end (process_submission.process + build_index) on a
   copy of the real feed
"""
import copy
import json
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FIX = ROOT / "tests" / "fixtures"
sys.path.insert(0, str(ROOT / "scripts"))
from packaging.specifiers import SpecifierSet  # noqa: E402
from packaging.version import Version  # noqa: E402

from reports.feed import build_index  # noqa: E402
from reports.process_submission import process  # noqa: E402
from reports.validate import check, parse_constraints  # noqa: E402

ALPHA = (FIX / "constraints-alpha.txt").read_text()
ALPHA_NOW = {"ovos-core": "3.7.2a1", "ovos-workshop": "9.8.9a2"}
BASE = {
    "schema": "ovos-test-report/1", "tool": "ovos-tui-client 0.3.0",
    "created_at": "2026-10-04T18:12:00Z", "channel": "alpha",
    "skill": {"package": "ovos-skill-convert", "version": "0.0.8", "skill_id": "ovos-skill-convert.andlo"},
    "stack": {"ovos-core": "3.7.2a1", "ovos-workshop": "9.8.9a2", "python": "3.11.2"},
    "setup": {"hardware": "Raspberry Pi 5", "languages": ["en-US"], "notes": "nothing special"},
    "outcome": "works", "level": 3,
    "loaded": {"ok": True, "languages": ["en-US"], "registrations": {"intents": 6}},
    "utterances": {"source": "test/end2end/golden_utterances_en-US.jsonl", "total": 10, "routed": 9, "answered": 9},
    "results": [{"utterance": "convert 10 cm to inches", "lang": "en-US", "expected": "x", "routed_to": "x", "spoke": True}],
}


def setp(path, value):
    def f(r):
        *parents, last = path.split(".")
        d = r
        for k in parents:
            d = d[k]
        d[last] = value
    return f


def pop(key):
    return lambda r: r.pop(key)


# name, mutation, latest release, channel stack, expected (status, passes, a code that must appear)
CASES = [
    ("clean current pass", None, "0.0.8", ALPHA_NOW, ("current", True, None)),
    ("older skill version", None, "0.0.9", ALPHA_NOW, ("stale", None, "old_version")),
    ("core no longer allowed", setp("stack.ovos-core", "2.0.0"), "0.0.8", ALPHA_NOW, ("stale", None, "old_stack")),
    ("older alpha, floor still ok", setp("stack.ovos-core", "3.5.0a4"), "0.0.8", ALPHA_NOW, ("stale", None, "old_stack")),
    ("same alpha minor, newer patch", setp("stack.ovos-core", "3.7.5a1"), "0.0.8", ALPHA_NOW, ("current", True, None)),
    ("channel stack unknown: constraints only", setp("stack.ovos-core", "3.5.0a4"), "0.0.8", None, ("current", True, None)),
    ("unknown channel", setp("channel", "unknown"), "0.0.8", ALPHA_NOW, ("stale", None, "no_channel")),
    ("below 80%", setp("utterances.routed", 5), "0.0.8", ALPHA_NOW, ("current", False, "below_level3")),
    ("did not load", setp("loaded.ok", False), "0.0.8", ALPHA_NOW, ("current", False, "not_loaded")),
    ("doesnt_work: counts, no pass", setp("outcome", "doesnt_work"), "0.0.8", ALPHA_NOW, ("current", False, None)),
    ("routed > total", setp("utterances.routed", 11), "0.0.8", ALPHA_NOW, ("invalid", False, "inconsistent")),
    ("wrong schema", setp("schema", "klondike-report/1"), "0.0.8", ALPHA_NOW, ("invalid", False, "schema")),
    ("wrong skill", setp("skill.package", "ovos-skill-other"), "0.0.8", ALPHA_NOW, ("invalid", False, "wrong_skill")),
    ("ip address", setp("setup.notes", "my box is 192.168.65.231"), "0.0.8", ALPHA_NOW, ("invalid", False, "private_ip")),
    ("home path", setp("setup.notes", "installed in /home/andlo/venv"), "0.0.8", ALPHA_NOW, ("invalid", False, "private_path")),
    ("e-mail", setp("setup.notes", "ask me at a@b.dk"), "0.0.8", ALPHA_NOW, ("invalid", False, "private_email")),
    ("api key", setp("setup.notes", "api_key: abcdef1234567890"), "0.0.8", ALPHA_NOW, ("invalid", False, "private_secret")),
    ("dotted version is not an ip", setp("stack.python", "3.11.2.1"), "0.0.8", ALPHA_NOW, ("current", True, None)),
    ("missing loaded", pop("loaded"), "0.0.8", ALPHA_NOW, ("invalid", False, "missing")),
    ("level 3 without utterances", pop("utterances"), "0.0.8", ALPHA_NOW, ("invalid", False, "missing")),
]


def build_cases():
    out = []
    for name, mut, latest, stack, want in CASES:
        r = copy.deepcopy(BASE)
        if mut:
            mut(r)
        out.append({"name": name, "report": r, "latest": latest, "stack": stack, "want": want})
    return out


def key(res):
    return res["status"], res["passes"], sorted(p["code"] for p in res["problems"])


def matches(res, want):
    status, passes, code = want
    codes = [p["code"] for p in res["problems"]]
    return res["status"] == status and (passes is None or res["passes"] == passes) \
        and (code is None or code in codes)


def node(script, payload):
    proc = subprocess.run(["node", "-e", script], input=json.dumps(payload), capture_output=True, text=True)
    if proc.returncode:
        raise SystemExit(proc.stderr)
    return json.loads(proc.stdout)


def test_validate(cases):
    fails = 0
    for c in cases:
        res = check(c["report"], "ovos-skill-convert", c["latest"], ALPHA, c["stack"])
        ok = matches(res, c["want"])
        fails += not ok
        print(("ok  " if ok else "FAIL"), "validate:", c["name"], key(res))
    return fails


def test_parity(cases):
    js = json.dumps(str(ROOT / "docs" / "reports.js"))
    got = node(f"""
      const {{checkReport}} = require({js});
      const cases = JSON.parse(require('fs').readFileSync(0, 'utf8'));
      const C = {json.dumps(ALPHA)};
      console.log(JSON.stringify(cases.map(c => checkReport(c.report, {{packageName: 'ovos-skill-convert',
        latestVersion: c.latest, constraintsText: C, channelStack: c.stack}}))));
    """, cases)
    fails = 0
    for c, b in zip(cases, got):
        a = check(c["report"], "ovos-skill-convert", c["latest"], ALPHA, c["stack"])
        if key(a) != key(b):
            fails += 1
            print("FAIL parity:", c["name"], "python", key(a), "js", key(b))
    probe = ["0.9.0", "1.3.1", "1.3.9", "1.4.0", "1.4.0a1", "2.2.4a1", "2.2.4", "3.7.2a1", "3.7.2",
             "3.8.0a1", "9.8.9a2", "0.10.0", "1.0.0.post1", "2.0.0.dev1"]
    pairs = [(v, spec) for ch in ("stable", "alpha")
             for spec in parse_constraints((FIX / f"constraints-{ch}.txt").read_text()).values() if spec
             for v in probe]
    allowed = node(f"""
      const {{pepAllowed}} = require({js});
      const pairs = JSON.parse(require('fs').readFileSync(0, 'utf8'));
      console.log(JSON.stringify(pairs.map(([v, s]) => pepAllowed(v, s))));
    """, pairs)
    pep_fails = 0
    for (v, s), j in zip(pairs, allowed):
        try:
            p = Version(v) in SpecifierSet(s, prereleases=True)
        except Exception:  # noqa: BLE001 - a spec packaging itself rejects
            continue
        if p != j:
            pep_fails += 1
            print("FAIL pep:", v, s, "packaging", p, "js", j)
    print(f"{'ok  ' if not fails else 'FAIL'} parity: {len(cases) - fails}/{len(cases)} cases")
    print(f"{'ok  ' if not pep_fails else 'FAIL'} pep 440: {len(pairs) - pep_fails}/{len(pairs)} pairs")
    return fails + pep_fails


def test_submission():
    docs = Path(tempfile.mkdtemp()) / "docs"
    (docs / "compat").mkdir(parents=True)
    shutil.copy(ROOT / "docs" / "skills.json", docs / "skills.json")
    feed = json.loads((docs / "skills.json").read_text())
    entry = next(e for e in feed if e.get("package_name") == "ovos-skill-convert")
    (docs / "compat" / "results.json").write_text(json.dumps(
        {"channels": {"alpha": {"stack": {"packages": ALPHA_NOW}}}, "results": {}}))
    offline = {"fetch_text": lambda url: ALPHA, "latest": lambda pkg: "0.0.8"}

    def env(report, **kw):
        body = f"### Entry\n\n{entry['id']}\n\n### Report\n\n```json\n" + \
            (report if isinstance(report, str) else json.dumps(report, indent=2)) + "\n```\n"
        e = {"ISSUE_TITLE": f"Test report: {entry['id']}", "ISSUE_BODY": body, "ISSUE_USER": "someone",
             "ISSUE_NUMBER": "42", "USER_CREATED_AT": "2020-01-01T00:00:00Z", "IS_MAINTAINER": "false"}
        e.update(kw)
        return e

    r = copy.deepcopy(BASE)
    bad = copy.deepcopy(BASE)
    bad["outcome"], bad["setup"] = "doesnt_work", {"hardware": "Mark 2", "notes": "crashes in da-dk"}
    steps = [
        ("stored", env(r), "stored"),
        ("second user, doesn't work", env(bad, ISSUE_USER="other"), "stored"),
        ("maintainer is pointed to their repo", env(r, IS_MAINTAINER="true"), "maintainer"),
        ("young account", env(r, USER_CREATED_AT=datetime.now(timezone.utc).isoformat()), "young_account"),
        ("not json", env("{not json"), "invalid"),
        ("unknown entry", env(r, ISSUE_BODY="### Entry\n\nno-such-entry\n\n### Report\n\n{}",
                              ISSUE_TITLE="Test report: no-such-entry"), "invalid"),
        ("private data", env({**r, "setup": {"notes": "at 192.168.1.20"}}), "invalid"),
        ("old version", env({**r, "skill": {**r["skill"], "version": "0.0.1"}}), "stale"),
        ("odd user name", env(r, ISSUE_USER="x/../y"), "invalid"),
    ]
    fails = 0
    for name, e, want in steps:
        out, rep, rel = process(e, docs, **offline)
        ok = out["verdict"] == want
        fails += not ok
        print(("ok  " if ok else "FAIL"), "submission:", name, out["verdict"])
        if rep is not None:
            (docs / rel).parent.mkdir(parents=True, exist_ok=True)
            (docs / rel).write_text(json.dumps(rep))
    index = build_index(feed, docs / "reports", {"alpha": ALPHA, "stable": None, "testing": None},
                        {"alpha": ALPHA_NOW}, lambda pkg: "0.0.8")
    c = index["entries"][entry["id"]]["alpha"]["community"]
    ok = (c["works"], c["doesnt_work"], c["history"]) == (1, 1, 0)
    fails += not ok
    print(("ok  " if ok else "FAIL"), "index:", {k: c[k] for k in ("works", "partly", "doesnt_work", "history")})
    # A new release makes both history without anyone touching them.
    later = build_index(feed, docs / "reports", {"alpha": ALPHA}, {"alpha": ALPHA_NOW}, lambda pkg: "0.0.9")
    c = later["entries"][entry["id"]]["alpha"]["community"]
    ok = (c["works"], c["history"]) == (0, 2)
    fails += not ok
    print(("ok  " if ok else "FAIL"), "index after a new release:", {k: c[k] for k in ("works", "history")})
    return fails


def test_crawler():
    from reports.crawler import sync_maintainer_reports
    reports = Path(tempfile.mkdtemp())
    entry = {"id": "andlo-ovos-skill-convert"}
    good = json.dumps(BASE)
    private = json.dumps({**BASE, "setup": {"notes": "see /home/andlo/notes"}})
    files = {"test/reports/alpha.json": good, "test/reports/stable.json": private}
    fails = 0
    got = sync_maintainer_reports("andlo/ovos-skill-convert", entry, lambda repo, p: files.get(p), reports)
    ok = got == {"alpha": "stored", "stable": "invalid"}
    stub = json.loads((reports / entry["id"] / "maintainer-stable.json").read_text())
    ok &= "invalid" in stub["_klondike"] and "/home/" not in json.dumps(stub)
    fails += not ok
    print(("ok  " if ok else "FAIL"), "crawler: store + private-data stub", got)
    files.pop("test/reports/alpha.json")
    got = sync_maintainer_reports("andlo/ovos-skill-convert", entry, lambda repo, p: files.get(p), reports)
    ok = got.get("alpha") == "removed" and not (reports / entry["id"] / "maintainer-alpha.json").exists()
    fails += not ok
    print(("ok  " if ok else "FAIL"), "crawler: file gone from the repo is removed", got)
    return fails


if __name__ == "__main__":
    cases = build_cases()
    failed = test_validate(cases) + test_parity(cases) + test_submission() + test_crawler()
    print("\nALL OK" if not failed else f"\n{failed} FAILED")
    sys.exit(1 if failed else 0)
