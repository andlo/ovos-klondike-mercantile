#!/usr/bin/env python3
"""Pipeline plugins at level 3 (#52), without OVOS or the network:

1. route.loaded_stages keeps only the stages whose plugin the intent service loaded
2. the profile overview lists what the routing runs left out, notes excluded
3. route.matched_pipeline reads which plugin matched (ovos-core 3), None before
4. publish sums what each plugin reached and took in the Klondike job
5. the overview gives a profile pipeline plugin Gold only when measured,
   reaching and taking nothing
"""
import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "scripts" / "compat"))
# route.py imports the routing judge at module level; the function under
# test does not use it.
judge = types.ModuleType("ovos_routing_judge")
judge.Claim = judge.intent_matches = judge.judge = object
judge.__version__ = "test"
sys.modules.setdefault("ovos_routing_judge", judge)

import route  # noqa: E402
from compat.profile_report import build  # noqa: E402
from compat.publish import pipeline_takes  # noqa: E402

fails = 0


def ok(cond, what):
    global fails
    print(("ok   " if cond else "FAIL ") + what)
    fails += not cond


class Croft:
    def __init__(self, loaded):
        self.intents = types.SimpleNamespace(pipeline_plugins={p: object() for p in loaded})


PIPE = ["ovos-stop-pipeline-plugin-high", "ovos-m2v-pipeline-high", "ovos-padatious-pipeline-plugin-high",
        "ovos-common-query-pipeline-plugin"]


def test_loaded_stages():
    keep, dropped = route.loaded_stages(Croft(["ovos-stop-pipeline-plugin", "ovos-padatious-pipeline-plugin",
                                               "ovos-common-query-pipeline-plugin"]), PIPE)
    ok(dropped == ["ovos-m2v-pipeline-high"], f"a plugin that failed to load is dropped ({dropped})")
    ok(keep == [s for s in PIPE if s != "ovos-m2v-pipeline-high"], "the rest keep their order")
    keep, dropped = route.loaded_stages(Croft([]), PIPE)
    ok(keep == PIPE and dropped == [], "nothing listed (old core): everything is kept")


def test_report():
    doc = {"generated_at": "t",
           "channels": {"testing": {"route": {"baseline_ids": ["x.y"], "pipeline_used": [],
                                              "pipeline_dropped": ["ovos-m2v-pipeline-high"]}},
                        "stable": {"route": {"baseline_ids": ["x.y"], "pipeline_used": [],
                                             "pipeline_dropped": ["(channel default used: 13 stages)"]}}},
           "results": {},
           "klondike": {"testing": {"profile": {"skill_ids": [], "curated": []},
                                    "job": {"results": {}, "boots": [{"pipeline_dropped": ["ovos-m2v-pipeline-high"]}]}},
                        "stable": {"profile": {"skill_ids": [], "curated": []}, "job": {"results": {}}}}}
    out = build(doc, [])
    ok(out["channels"]["testing"]["pipeline_not_loaded"] == ["ovos-m2v-pipeline-high"],
       "the overview lists the stage once")
    ok(out["channels"]["stable"]["pipeline_not_loaded"] == [], "a note is not a stage")


class Msg:
    def __init__(self, msg_type, data=None, context=None):
        self.msg_type, self.data, self.context = msg_type, data or {}, context or {}


def test_matched_pipeline():
    recs = [Msg("recognizer_loop:utterance"),
            Msg("ovos-skill-x.andlo:intent", context={"pipeline_id": "ovos-padatious-pipeline-plugin"}),
            Msg("ovos.intent.matched", {"pipeline_id": "ovos-padatious-pipeline-plugin"})]
    ok(route.matched_pipeline(recs) == "ovos-padatious-pipeline-plugin", "the matched plugin is read")
    ok(route.matched_pipeline(recs[:2]) == "ovos-padatious-pipeline-plugin", "from the dispatch context too")
    ok(route.matched_pipeline([Msg("recognizer_loop:utterance"), Msg("speak")]) is None,
       "an older core says nothing: None, not a plugin")


def test_takes_and_gold():
    reading = "ovos-common-reading-pipeline-plugin"
    results = {
        "a-grimm": {"routing": {"golden": {"by_pipeline": {reading: {"hit": 3, "miss": 0}}}}},
        "o-date": {"routing": {"golden": {
            "by_pipeline": {reading: {"hit": 0, "miss": 1}, "ovos-padatious-pipeline-plugin": {"hit": 9, "miss": 0}},
            "misses": [{"utterance": "tell me the time", "pipeline": reading,
                        "taken_by": "ovos-skill-grimm-tales.andlo", "kind": "baseline"}]}}},
    }
    r = pipeline_takes(results)[reading]
    ok(r["reaches"] == 3 and r["takes"] == 1 and r["examples"][0]["from"] == "o-date",
       f"reaches and takes are summed, with the sentence it took ({r})")

    def doc(attribution, takes):
        return {"generated_at": "t",
                "channels": {"alpha": {"route": {"baseline_ids": ["x.y"], "pipeline_used": []}}},
                "results": {"a-reading": {"alpha": {"plugin_ids": [reading], "status": "pass",
                                                    "level": 2, "kind": "pipeline"}}},
                "klondike": {"alpha": {"profile": {"skill_ids": [], "curated": [],
                                                   "added_stages": [reading + "-high"]},
                                       "job": {"results": {}, "attribution": attribution,
                                               "pipelines": {reading: {"reaches": 3, "takes": takes}}}}}}

    def entry(d):
        prof = next(p for p in build(d, [])["channels"]["alpha"]["profiles"] if p["id"] == "klondike")
        return next(e for e in prof["entries"] if e["store_id"] == "a-reading")
    e = entry(doc(True, 0))
    ok(e["gold"] and e["pipeline_route"]["reaches"] == 3, "measured, reaching, taking nothing: Gold")
    ok(not entry(doc(True, 1))["gold"], "taking one sentence: no Gold")
    e = entry(doc(False, 0))
    ok(not e["gold"] and e["pipeline_route"]["measured"] is False, "not measurable: no Gold, and it says so")


if __name__ == "__main__":
    test_loaded_stages()
    test_report()
    test_matched_pipeline()
    test_takes_and_gold()
    print("\nALL OK" if not fails else f"\n{fails} FAILED")
    sys.exit(1 if fails else 0)
