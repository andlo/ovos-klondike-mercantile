#!/usr/bin/env python3
"""Golden counts per language, so channels that routed different languages
can be compared on the ones they share (the compare view), without OVOS:

1. aggregate() keeps hit/counted per routed language next to the totals
2. publish keeps by_lang and drops entries that don't add up
3. the profile report passes langs and by_lang on to the compare view
4. level 3 is decided on the en-US rows (#67), with the totals as fallback
   for results from before the per-language counts
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts" / "compat"))
sys.path.insert(0, str(ROOT / "scripts"))

import run_shard  # noqa: E402
import publish  # noqa: E402
from feed import label, level3_counts  # noqa: E402
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
ok(g.get("by_lang") == {"en-US": {"hit": 1, "counted": 12, "taken": 0}, "da-DK": {"hit": 2, "counted": 12, "taken": 0}},
   "by_lang: per language, without manual rows, and no entry for a language with nothing counted")

# 2. publish
clean = publish._clean_run({**g, "by_lang": {**g["by_lang"], "xx": {"hit": 5, "counted": 2}, "yy": "bad"}})
ok(clean.get("by_lang") == g["by_lang"], "publish keeps valid per-language counts and drops the rest")
ok("by_lang" not in publish._clean_run({k: v for k, v in g.items() if k != "by_lang"}),
   "a result from before by_lang publishes without it")

# 3. profile report
out = row("a.skill", "skill", "a-skill", {**rec, "level": 2, "status": "pass"}, None)
ok(out["golden"].get("langs") == ["en-US"] and out["golden"]["counted"] == 12 and out["golden"].get("by_lang") == g["by_lang"],
   "the report counts en-US and carries the per-language counts")

# 4. level 3 on en-US
def run_of(boots_, langs):
    rec_ = {"routing": {"golden": {"status": "ok"}}, "level": 2}
    run_shard.aggregate([(item, rec_)], boots_, langs, [], "routing")
    return rec_

en_ok = [{"lang": "en-US", "results": {"a-skill": {"golden": counts(10, 12)}}},
         {"lang": "de-DE", "results": {"a-skill": {"golden": counts(0, 12, hang=12)}}}]
r1 = run_of(en_ok, ["en-US", "de-DE"])
ok(r1["level"] == 3, "10/12 in en-US is level 3, even with German at 0/12 (10/24 in all)")
ok(publish.routing_level3(publish.clean_routing(r1["routing"])), "publish re-derives the same level 3")
ok(label({**r1, "status": "pass"})[0].startswith("✓ 10/12 golden"), "the label shows the en-US count")

no_en = [{"lang": "da-DK", "results": {"a-skill": {"golden": counts(12, 12)}}}]
r2 = run_of(no_en, ["da-DK"])
ok(r2["level"] == 2 and level3_counts(r2["routing"]["golden"]) is None,
   "no en-US golden utterances: no level 3, however the other languages do")

en_bad = [{"lang": "en-US", "results": {"a-skill": {"golden": counts(2, 12, hang=10)}}},
          {"lang": "da-DK", "results": {"a-skill": {"golden": counts(40, 40)}}}]
r3 = run_of(en_bad, ["en-US", "da-DK"])
ok(r3["level"] == 2, "2/12 in en-US is not level 3, even with 42/52 in all")

old = {"status": "ok", "hit": 9, "counted": 10, "total": 10, "langs": ["en-US", "da-DK"]}
ok(level3_counts(old) == (9, 10) and publish.routing_level3({"golden": old}),
   "a result from before by_lang keeps its totals")

print(f"\n{'FAILED: ' + str(fails) if fails else 'ALL OK'}")
sys.exit(1 if fails else 0)
