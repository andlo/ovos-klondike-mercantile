#!/usr/bin/env python3
"""Golden counts per language, so channels that routed different languages
can be compared on the ones they share (the compare view), without OVOS:

1. aggregate() keeps hit/counted per routed language next to the totals
2. publish keeps by_lang and drops entries that don't add up
3. the profile report passes langs and by_lang on to the compare view
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts" / "compat"))
sys.path.insert(0, str(ROOT / "scripts"))

import run_shard  # noqa: E402
import publish  # noqa: E402
from compat.profile_report import row  # noqa: E402

fails = 0


def ok(cond, what):
    global fails
    print(("ok   " if cond else "FAIL ") + what)
    fails += not cond


def counts(hit, total, hang=0, manual=0):
    return {"hit": hit, "total": total, "hang": hang, "manual": manual, "misses": []}


# 1. aggregate
item = {"id": "a-skill"}
rec = {"routing": {"golden": {"status": "ok"}}}
boots = [
    {"lang": "en-US", "results": {"a-skill": {"golden": counts(1, 12, hang=11)}}},
    {"lang": "da-DK", "results": {"a-skill": {"golden": counts(2, 13, hang=10, manual=1)}}},
    {"lang": "de-DE", "results": {"a-skill": {"golden": counts(0, 2, manual=2)}}},
]
run_shard.aggregate([(item, rec)], boots, ["en-US", "da-DK", "de-DE"], [], "routing")
g = rec["routing"]["golden"]
ok(g["counted"] == 24 and g["hit"] == 3, "totals are summed over the languages")
ok(g.get("by_lang") == {"en-US": {"hit": 1, "counted": 12}, "da-DK": {"hit": 2, "counted": 12}},
   "by_lang: per language, without manual rows, and no entry for a language with nothing counted")

# 2. publish
clean = publish._clean_run({**g, "by_lang": {**g["by_lang"], "xx": {"hit": 5, "counted": 2}, "yy": "bad"}})
ok(clean.get("by_lang") == g["by_lang"], "publish keeps valid per-language counts and drops the rest")
ok("by_lang" not in publish._clean_run({k: v for k, v in g.items() if k != "by_lang"}),
   "a result from before by_lang publishes without it")

# 3. profile report
out = row("a.skill", "skill", "a-skill", {**rec, "level": 2, "status": "pass"}, None)
ok(out["golden"].get("langs") == ["en-US", "da-DK", "de-DE"] and out["golden"].get("by_lang") == g["by_lang"],
   "the report carries the languages and the per-language counts")

print(f"\n{'FAILED: ' + str(fails) if fails else 'ALL OK'}")
sys.exit(1 if fails else 0)
