#!/usr/bin/env python3
"""A fallback of last resort (#75), graded by level 2. Run: python3 tests/test_last_resort.py
(the parity check needs `node`; it is skipped without it)

1. probe records a skill's fallback priority from its registration
2. route counts `taken`: rows another skill took, or a stage other than the fallbacks
3. aggregate and publish carry `taken` per language, and the priority
4. the rule: low band (priority above 90) and at least half taken, en-US;
   application-launcher (priority 4) and a broken fallback are not marked
5. label, compact and the profile report row: no golden counts, a note
6. plan retests a fallback skill tested before the priority was recorded, once
7. docs/shared.js gives the same label as feed.py on the same records
"""
import json
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "scripts" / "compat"))

from compat import plan, publish, run_shard  # noqa: E402
from compat.feed import LAST_RESORT_LABEL, compact, label, last_resort  # noqa: E402
from compat.profile_report import row  # noqa: E402
from probe import Recorder  # noqa: E402

fails = 0


def ok(cond, what):
    global fails
    print(("ok   " if cond else "FAIL ") + what)
    fails += not cond


def golden(hit, counted, taken, lang="en-US"):
    return {"status": "ok", "hit": hit, "counted": counted, "total": counted, "baseline": taken,
            "taken": taken, "by_lang": {lang: {"hit": hit, "counted": counted, "taken": taken}}}


def rec(prio, g, status="pass", **kw):
    r = {"status": status, "kind": "skill", "level": 2, "plugin_ids": ["s.x"],
         "registrations": {"fallback": 1}, "routing": {"golden": g}, **kw}
    if prio is not None:
        r["fallback_priority"] = prio
    return r


# 1. probe
r = Recorder(["unknown.x"])
r(json.dumps({"type": "ovos.skills.fallback.register", "data": {"skill_id": "unknown.x", "priority": 100}}))
r(json.dumps({"type": "ovos.skills.fallback.register", "data": {"skill_id": "other.x", "priority": 4}}))
ok(r.fallback_priorities == [100] and r.summary()[0] == {"fallback": 1},
   "probe: its own fallback registration and its priority, not another skill's")
r = Recorder(["a.x"])
r(json.dumps({"type": "ovos.skills.fallback.register", "data": {"skill_id": "a.x", "priority": 95}}))
r(json.dumps({"type": "ovos.skills.fallback.register", "data": {"skill_id": "a.x", "priority": 30}}))
r(json.dumps({"type": "ovos.skills.fallback.register", "data": {"skill_id": "a.x"}}))
ok(min(r.fallback_priorities) == 30 and 101 in r.fallback_priorities,
   "probe: the lowest of several; no priority reads as 101, as ovos-core does")

# 2. route
import route  # noqa: E402  (needs ovos-routing-judge, as the shard does)
ok(route.stage_took("ovos-persona-pipeline-plugin") and route.stage_took("ovos-common-query-pipeline-plugin"),
   "route: persona and common query count as a stage that took it")
ok(not any(route.stage_took(s) for s in (None, "", "ovos-fallback-pipeline-plugin-low",
                                         "last message: ovos.skills.fallback.pong", "stop-pipeline-plugin-high")),
   "route: a fallback stage, the last message or nothing doesn't")

# 3. aggregate and publish
item, r = {"id": "unknown"}, {"routing": {"golden": {"status": "ok"}}}
boots = [{"lang": "en-US", "results": {"unknown": {"golden": {"hit": 0, "total": 9, "baseline": 8, "taken": 9,
                                                              "unhandled": 1, "misses": []}}}},
         {"lang": "ca-ES", "results": {"unknown": {"golden": {"hit": 0, "total": 7, "baseline": 3, "taken": 3,
                                                              "neighbour": 3, "hang": 1, "misses": []}}}}]
run_shard.aggregate([(item, r)], boots, ["en-US", "ca-ES"], [], "routing")
g = r["routing"]["golden"]
ok(g["taken"] == 12 and g["by_lang"] == {"en-US": {"hit": 0, "counted": 9, "taken": 9},
                                         "ca-ES": {"hit": 0, "counted": 4, "taken": 3}},
   "aggregate: taken summed, and per language")
c = publish._clean_run(g)
ok(c["taken"] == 12 and c["by_lang"]["en-US"]["taken"] == 9, "publish keeps taken")
bad = publish._clean_run({**g, "by_lang": {"en-US": {"hit": 5, "counted": 9, "taken": 6}}})
ok(bad["by_lang"]["en-US"] == {"hit": 5, "counted": 9}, "publish drops a taken that doesn't add up (hit + taken > counted)")
base = {"id": "x", "channel": "alpha", "key": "k", "status": "pass", "level": 2}
ok(publish.clean({**base, "fallback_priority": 100})["fallback_priority"] == 100
   and "fallback_priority" not in publish.clean({**base, "fallback_priority": "100"})
   and "fallback_priority" not in publish.clean({**base, "fallback_priority": True}),
   "publish keeps an int priority, nothing else")

# 4. the rule
unknown = rec(100, golden(0, 9, 9))                  # fallback-unknown on alpha
launcher = rec(4, golden(0, 16, 15))                  # application-launcher: priority 4
ddg = rec(90, golden(0, 8, 8))                        # 90 is still the medium band
broken = rec(100, golden(0, 9, 2))                    # mostly silent: points at itself
half = rec(91, golden(0, 8, 4))
old = rec(100, {"status": "ok", "hit": 0, "counted": 9, "by_lang": {"en-US": {"hit": 0, "counted": 9}}})
other_lang = rec(100, golden(0, 9, 9, lang="ca-ES"))
ok(last_resort(unknown) and last_resort(half), "a low-band fallback taken at least half the time is a last resort")
ok(not last_resort(launcher), "a high-band fallback (application-launcher, 4) is not, however much is taken")
ok(not last_resort(ddg), "priority 90 is the medium band: not")
ok(not last_resort(broken), "a broken one (taken 2/9) is not: its misses point at itself")
ok(not last_resort(old), "a result from before taken was counted is not (it is retested)")
ok(not last_resort(other_lang), "decided on en-US, like level 3")
ok(not last_resort(rec(None, golden(0, 9, 9))), "no recorded priority: not")
ok(not last_resort({**unknown, "status": "fail", "level": 1}), "one that doesn't load is not")

# 5. labels and the report row
ok(label(unknown) == (LAST_RESORT_LABEL, "pass"), "label: ✓ loads · last-resort fallback, pass")
ok(label({**unknown, "warnings": ["w"]}) == (LAST_RESORT_LABEL, "warn"), "label: warn with a load warning")
ok(label({**unknown, "status": "fail", "level": 1}) == ("✗ doesn't load", "fail"), "label: level 2 still decides")
ok(label(launcher) == ("✓ loads · 0/16 golden", "warn"), "label: application-launcher keeps its golden count")
cu = compact(unknown)
ok(cu.get("last_resort") is True and "golden" not in cu and cu["level"] == 2, "compact: no golden counts, last_resort")
ok("golden" in compact(launcher) and "last_resort" not in compact(launcher), "compact: others unchanged")
kres = {"routing": {"golden": golden(0, 9, 9)}}
pr = row("unknown.x", "skill", "unknown", unknown, kres, note="curated")
ok(pr["label"] == LAST_RESORT_LABEL and pr["state"] == "pass" and pr["golden"] is None and pr["klondike"] is None
   and pr["note"].startswith("curated; a fallback of last resort"), "profile report: level 2, no counts, a note")
pl = row("launcher.x", "skill", "launcher", launcher, None)
ok(pl["golden"] == {"hit": 0, "counted": 16, "langs": ["en-US"], "by_lang": launcher["routing"]["golden"]["by_lang"]}
   and "note" not in pl, "profile report: application-launcher unchanged")

# 6. plan
before = {"status": "pass", "registrations": {"fallback": 1}, "tested_at": "2026-10-05T03:00:00+00:00"}
ok(plan.needs_fallback_priority(before), "plan: a fallback skill tested before the priority was recorded is retested")
ok(not plan.needs_fallback_priority({**before, "fallback_priority": 100}), "plan: not once it has one")
ok(not plan.needs_fallback_priority({**before, "tested_at": "2026-10-10T03:00:00+00:00"}),
   "plan: not one tested since without a priority (never in a loop)")
ok(not plan.needs_fallback_priority({**before, "registrations": {"intents": 3}}), "plan: not a skill without a fallback")

# 7. parity with docs/shared.js
cases = [unknown, {**unknown, "warnings": ["w"]}, launcher, ddg, broken, half, old, other_lang,
         {**unknown, "routing": {**unknown["routing"], "stop": {"result": "stops"}}}]
if shutil.which("node"):
    proc = subprocess.run(["node", "-e", """
      const vm = require('vm'), fs = require('fs');
      vm.runInThisContext(fs.readFileSync(process.argv[1], 'utf8'));
      const cases = JSON.parse(fs.readFileSync(0, 'utf8'));
      console.log(JSON.stringify(cases.map(c => { const o = compatFromRecord(c);
        return [o.label, o.state, !!o.last_resort, !!o.golden]; })));
    """, str(ROOT / "docs" / "shared.js")], input=json.dumps(cases), capture_output=True, text=True)
    if proc.returncode:
        ok(False, "shared.js runs in node: " + proc.stderr[-300:])
    else:
        js = json.loads(proc.stdout)
        py = [[*label(c), last_resort(c), "golden" in compact(c)] for c in cases]
        bad = [(c.get("fallback_priority"), p, j) for c, p, j in zip(cases, py, js) if p != j]
        ok(not bad, "shared.js gives the same label, state and counts as feed.py" + (f": {bad}" if bad else ""))
else:
    print("skip parity: node not installed")

print("\nALL OK" if not fails else f"\nFAILED: {fails}")
sys.exit(1 if fails else 0)
