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
CONSTRAINTS = {ch: (FIX / f"constraints-{ch}.txt").read_text() for ch in ("stable", "testing", "alpha")}
ALPHA_NOW = {"ovos-core": "3.7.2a1", "ovos-workshop": "9.8.9a2"}
# What each channel installs today (as the compat run records it).
STACKS = {"stable": {"ovos-core": "1.3.1", "ovos-workshop": "3.4.0"},
          "testing": {"ovos-core": "2.1.1", "ovos-workshop": "7.0.6"},
          "alpha": ALPHA_NOW}
def setp(path, value):
    """Set a nested value; the path is split on "/" (skill ids contain dots)."""
    def f(r):
        *parents, last = path.split("/")
        d = r
        for k in parents:
            d = d[k]
        d[last] = value
    return f


def pop(key):
    return lambda r: r.pop(key)


SID = "ovos-skill-convert.andlo"


def _step(i, status, answered=True):
    return {"i": i, "utterance": f"convert {i} cm to inches", "lang": "en-us",
            "expected": f"{SID}:convert.intent", "status": status,
            "handled_by": f"{SID}:convert.intent" if status == "pass" else None, "answered": answered}


# Shaped like ovos-tui-client's --report output (docs/headless.md in #54).
BASE = {
    "schema": "ovos-test-report/1",
    "title": f"Test: {SID}",
    "manifest": {
        "created_at": "2026-10-04T18:12:00Z", "tool": "ovos-tui-client 0.3.0", "bus": "local",
        "channel": "alpha", "channel_source": "ovos-installer", "lang": "en-us",
        "machine": {"arch": "aarch64", "model": "Raspberry Pi 5 Model B Rev 1.0", "python": "3.11.2"},
        "versions_from": "this environment",
        "stack": {"ovos-core": "3.7.2a1", "ovos-workshop": "9.8.9a2"},
        "skills": {SID: {"package": "ovos-skill-convert", "version": "0.0.8", "active": True}},
        "config": {"lang": "en-us", "secondary_langs": ["da-dk"], "pipeline": ["ovos-padatious-pipeline-plugin-high"],
                   "stt": "ovos-stt-plugin-server", "tts": "ovos-tts-plugin-piper"},
    },
    "summary": {"steps": 10, "planned": 10, "checked": 10, "passed": 9, "failed": 1, "timed_out": 0,
                "sent_without_check": 0, "answered": 10, "cancelled": False, "duration_s": 42.0},
    "steps": [_step(i, "pass") for i in range(1, 10)] + [_step(10, "fail")],
    "notes": "nothing special",
}



def with_steps(passes, fails):
    def f(r):
        r["steps"] = [_step(i, "pass") for i in range(1, passes + 1)] + \
            [_step(passes + i, "fail") for i in range(1, fails + 1)]
        r["summary"].update(steps=passes + fails, checked=passes + fails, passed=passes, failed=fails)
    return f


CASES = [
    ("clean current pass (9/10)", None, "0.0.8", STACKS, ("current", False, None)),
    ("all routed", with_steps(10, 0), "0.0.8", STACKS, ("current", True, None)),
    ("older skill version", with_steps(10, 0), "0.0.9", STACKS, ("stale", None, "old_version")),
    ("core no longer allowed", setp("manifest/stack/ovos-core", "2.0.0"), "0.0.8", STACKS, ("stale", None, "old_stack")),
    ("older alpha, floor still ok", setp("manifest/stack/ovos-core", "3.5.0a4"), "0.0.8", STACKS, ("stale", None, "old_stack")),
    ("same alpha minor, newer patch", setp("manifest/stack/ovos-core", "3.7.5a1"), "0.0.8", STACKS, ("current", None, None)),
    ("channel stack unknown: constraints only", setp("manifest/stack/ovos-core", "3.5.0a4"), "0.0.8", {}, ("current", None, None)),
    ("no channel: inferred alpha from the versions", setp("manifest/channel", None), "0.0.8", STACKS, ("current", None, None, "alpha")),
    ("no channel: inferred testing", lambda r: (r["manifest"].update(channel=None), r["manifest"].update(stack={"ovos-core": "2.1.1", "ovos-workshop": "7.0.6"})), "0.0.8", STACKS, ("current", None, None, "testing")),
    ("no channel: inferred stable", lambda r: (r["manifest"].update(channel=None), r["manifest"].update(stack={"ovos-core": "1.3.1", "ovos-workshop": "3.4.0"})), "0.0.8", STACKS, ("current", None, None, "stable")),
    ("no channel: mixed stack matches none", lambda r: (r["manifest"].update(channel=None), r["manifest"].update(stack={"ovos-core": "3.7.2a1", "ovos-workshop": "7.0.6"})), "0.0.8", STACKS, ("stale", None, "no_channel")),
    ("says testing, runs alpha", setp("manifest/channel", "testing"), "0.0.8", STACKS, ("stale", None, "old_stack")),
    ("unknown channel name, runs alpha", setp("manifest/channel", "beta"), "0.0.8", STACKS, ("current", None, None, "alpha")),
    ("no versions (remote bus)", setp("manifest/stack", {}), "0.0.8", STACKS, ("stale", None, "no_stack")),
    ("below 80%", with_steps(5, 5), "0.0.8", STACKS, ("current", False, "below_level3")),
    ("not active", setp(f"manifest/skills/{SID}/active", False), "0.0.8", STACKS, ("current", False, "not_loaded")),
    ("nothing checked: level 2", with_steps(0, 0), "0.0.8", STACKS, ("current", True, None)),
    ("summary disagrees with steps", setp("summary/passed", 10), "0.0.8", STACKS, ("invalid", False, "inconsistent")),
    ("unknown step status", setp("steps", [{"utterance": "x", "status": "weird"}]), "0.0.8", STACKS, ("invalid", False, "type")),
    ("wrong schema", setp("schema", "klondike-report/1"), "0.0.8", STACKS, ("invalid", False, "schema")),
    ("wrong skill", setp(f"manifest/skills/{SID}/package", "ovos-skill-other"), "0.0.8", STACKS, ("invalid", False, "wrong_skill")),
    ("no skill version", setp(f"manifest/skills/{SID}/version", None), "0.0.8", STACKS, ("invalid", False, "missing")),
    ("ip address", setp("notes", "my box is 192.168.65.231"), "0.0.8", STACKS, ("invalid", False, "private_ip")),
    ("home path", setp("notes", "installed in /home/andlo/venv"), "0.0.8", STACKS, ("invalid", False, "private_path")),
    ("e-mail", setp("notes", "ask me at a@b.dk"), "0.0.8", STACKS, ("invalid", False, "private_email")),
    ("api key", setp("notes", "api_key: abcdef1234567890"), "0.0.8", STACKS, ("invalid", False, "private_secret")),
    ("replies included", lambda r: r["steps"][0].update(replies=["it is 14 degrees in Kvistgaard"]), "0.0.8", STACKS, ("invalid", False, "private_replies")),
    ("dotted versions are not ips", setp("manifest/machine/python", "3.11.2.1"), "0.0.8", STACKS, ("current", None, None)),
    ("no manifest", pop("manifest"), "0.0.8", STACKS, ("invalid", False, "missing")),
]


def build_cases():
    out = []
    for name, mut, latest, stack, want in CASES:
        r = copy.deepcopy(BASE)
        if mut:
            mut(r)
        out.append({"name": name, "report": r, "latest": latest, "stacks": stack, "want": want})
    return out


def key(res):
    return res["status"], res["passes"], sorted(p["code"] for p in res["problems"]), \
        (res.get("view") or {}).get("channel")


def matches(res, want):
    status, passes, code = want[:3]
    channel = want[3] if len(want) > 3 else None
    codes = [p["code"] for p in res["problems"]]
    return res["status"] == status and (passes is None or res["passes"] == passes) \
        and (code is None or code in codes) \
        and (channel is None or (res.get("view") or {}).get("channel") == channel)


def node(script, payload):
    proc = subprocess.run(["node", "-e", script], input=json.dumps(payload), capture_output=True, text=True)
    if proc.returncode:
        raise SystemExit(proc.stderr)
    return json.loads(proc.stdout)


def test_validate(cases):
    fails = 0
    v = check(copy.deepcopy(BASE), "ovos-skill-convert", "0.0.8", CONSTRAINTS, STACKS)["view"]
    ok = (v["stt"], v["tts"], v["hardware"]) == ("ovos-stt-plugin-server", "ovos-tts-plugin-piper",
                                                  "Raspberry Pi 5 Model B Rev 1.0")
    fails += not ok
    print(("ok  " if ok else "FAIL"), "validate: view carries hardware, stt and tts", v["stt"], v["tts"])
    for c in cases:
        res = check(c["report"], "ovos-skill-convert", c["latest"], CONSTRAINTS, c["stacks"])
        ok = matches(res, c["want"])
        fails += not ok
        print(("ok  " if ok else "FAIL"), "validate:", c["name"], key(res))
    return fails


def test_parity(cases):
    js = json.dumps(str(ROOT / "docs" / "reports.js"))
    got = node(f"""
      const {{checkReport}} = require({js});
      const cases = JSON.parse(require('fs').readFileSync(0, 'utf8'));
      const C = {json.dumps(CONSTRAINTS)};
      console.log(JSON.stringify(cases.map(c => checkReport(c.report, {{packageName: 'ovos-skill-convert',
        latestVersion: c.latest, constraints: C, channelStacks: c.stacks}}))));
    """, cases)
    fails = 0
    for c, b in zip(cases, got):
        a = check(c["report"], "ovos-skill-convert", c["latest"], CONSTRAINTS, c["stacks"])
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


def pack(report):
    import base64, gzip
    raw = json.dumps(report, separators=(",", ":")).encode()
    return "ovos-test-report/1+gzip:" + base64.urlsafe_b64encode(gzip.compress(raw)).decode().rstrip("=")


def test_submission():
    docs = Path(tempfile.mkdtemp()) / "docs"
    (docs / "compat").mkdir(parents=True)
    shutil.copy(ROOT / "docs" / "skills.json", docs / "skills.json")
    feed = json.loads((docs / "skills.json").read_text())
    entry = next(e for e in feed if e.get("package_name") == "ovos-skill-convert")
    (docs / "compat" / "results.json").write_text(json.dumps(
        {"channels": {ch: {"stack": {"packages": st}} for ch, st in STACKS.items()}, "results": {}}))
    def fetch_constraints(url):
        return CONSTRAINTS[url.rsplit("constraints-", 1)[1].removesuffix(".txt")]
    offline = {"fetch_text": fetch_constraints, "latest": lambda pkg: "0.0.8"}

    def env(report, **kw):
        body = f"### Entry\n\n{entry['id']}\n\n### Report\n\n```json\n" + \
            (report if isinstance(report, str) else json.dumps(report, indent=2)) + "\n```\n"
        e = {"ISSUE_TITLE": f"Test report: {entry['id']}", "ISSUE_BODY": body, "ISSUE_USER": "someone",
             "ISSUE_NUMBER": "42", "USER_CREATED_AT": "2020-01-01T00:00:00Z", "IS_MAINTAINER": "false"}
        e.update(kw)
        return e

    r = copy.deepcopy(BASE)
    with_steps(10, 0)(r)
    bad = copy.deepcopy(BASE)
    with_steps(0, 10)(bad)
    bad["manifest"]["machine"]["model"], bad["notes"] = "Mark 2", "crashes in da-dk"
    old_version = copy.deepcopy(r)
    setp(f"manifest/skills/{SID}/version", "0.0.1")(old_version)
    steps = [
        ("stored", env(r), "stored"),
        ("packed (from the Submit button, too long for plain JSON)", env(pack(r), ISSUE_USER="packer"), "stored"),
        ("packed but broken", env("ovos-test-report/1+gzip:not-base64!!", ISSUE_USER="packer2"), "invalid"),
        ("second user, doesn't work", env(bad, ISSUE_USER="other"), "stored"),
        ("maintainer is pointed to their repo", env(r, IS_MAINTAINER="true"), "maintainer"),
        ("young account", env(r, USER_CREATED_AT=datetime.now(timezone.utc).isoformat()), "young_account"),
        ("not json", env("{not json"), "invalid"),
        ("unknown entry", env(r, ISSUE_BODY="### Entry\n\nno-such-entry\n\n### Report\n\n{}",
                              ISSUE_TITLE="Test report: no-such-entry"), "invalid"),
        ("private data", env({**r, "notes": "at 192.168.1.20"}), "invalid"),
        ("old version", env(old_version), "stale"),
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
    index = build_index(feed, docs / "reports", CONSTRAINTS, STACKS, lambda pkg: "0.0.8")
    c = index["entries"][entry["id"]]["alpha"]["community"]
    ok = (c["works"], c["doesnt_work"], c["history"]) == (2, 1, 0)   # "someone", "packer"; "other"
    fails += not ok
    print(("ok  " if ok else "FAIL"), "index:", {k: c[k] for k in ("works", "partly", "doesnt_work", "history")})
    # A new release makes both history without anyone touching them.
    later = build_index(feed, docs / "reports", CONSTRAINTS, STACKS, lambda pkg: "0.0.9")
    c = later["entries"][entry["id"]]["alpha"]["community"]
    ok = (c["works"], c["history"]) == (0, 3)
    fails += not ok
    print(("ok  " if ok else "FAIL"), "index after a new release:", {k: c[k] for k in ("works", "history")})
    return fails


def test_crawler():
    from reports.crawler import sync_maintainer_reports
    reports = Path(tempfile.mkdtemp())
    entry = {"id": "andlo-ovos-skill-convert"}
    good = json.dumps(BASE)
    private = json.dumps({**BASE, "notes": "see /home/andlo/notes"})
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
