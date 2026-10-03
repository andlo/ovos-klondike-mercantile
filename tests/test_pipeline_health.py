#!/usr/bin/env python3
"""A stage of the installer's pipeline that does not load is reported (#52),
without OVOS or the network:

1. route.loaded_stages keeps only the stages whose plugin the intent service loaded
2. the profile overview lists what the routing runs left out, notes excluded
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


if __name__ == "__main__":
    test_loaded_stages()
    test_report()
    print("\nALL OK" if not fails else f"\n{fails} FAILED")
    sys.exit(1 if fails else 0)
