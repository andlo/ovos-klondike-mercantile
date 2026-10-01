#!/usr/bin/env python3
"""Provider skills at level 3, without the network:

1. level 2 records a common-reading provider as such
2. a shard routing one gets the reading pipeline installed and its stages
   inserted; a shard without one is left alone
3. the claimant of a row is the provider the reading pipeline asked for
   the content, since a provider fires no intent of its own
"""
import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "scripts" / "compat"))

from compat.baseline import with_companions  # noqa: E402
from compat.probe import classify  # noqa: E402

INSTALLER = ["ovos-stop-pipeline-plugin-high", "ovos-converse-pipeline-plugin",
             "ovos-padatious-pipeline-plugin-high", "ovos-fallback-pipeline-plugin-low"]
fails = 0


def ok(cond, what):
    global fails
    print(("ok   " if cond else "FAIL ") + what)
    fails += not cond


def test_level2_records_providers():
    ok(classify("ovos.common_reading.vocabulary") == "common_reading", "vocabulary announcement")
    ok(classify("ovos.common_reading.ping") == "common_reading", "any common_reading topic")
    ok(classify("question:query.response") is None, "other topics unchanged")


def test_companions():
    spec = {"requirements": ["ovos-core[skills-essential]"], "pipeline": list(INSTALLER), "exclude_ids": []}
    same, added = with_companions(spec, [{"intents": 4}, None, {"common_query": 1}])
    ok(same is spec and added == {}, "no provider: spec untouched")

    out, added = with_companions(spec, [{"intents": 4}, {"common_reading": 2, "other": ["x"]}])
    ok("ovos-common-reading-pipeline-plugin" in out["requirements"], "plugin installed")
    ok(out["pipeline"] == ["ovos-stop-pipeline-plugin-high", "ovos-common-reading-pipeline-plugin-high",
                           "ovos-converse-pipeline-plugin", "ovos-padatious-pipeline-plugin-high",
                           "ovos-common-reading-pipeline-plugin-low", "ovos-fallback-pipeline-plugin-low"],
       f"high after stop, low before fallback ({out['pipeline']})")
    ok(spec["pipeline"] == INSTALLER and len(spec["requirements"]) == 1, "input spec not mutated")
    ok(added == {"common_reading": ["ovos-common-reading-pipeline-plugin-high",
                                    "ovos-common-reading-pipeline-plugin-low"]}, "stages reported")

    twice, _ = with_companions(out, [{"common_reading": 1}])
    ok(twice["pipeline"] == out["pipeline"] and twice["requirements"].count(
        "ovos-common-reading-pipeline-plugin") == 1, "applying twice changes nothing")


def test_claimant():
    try:
        from route import claimant
    except Exception as e:  # noqa: BLE001 - route.py needs the test venv's ovos packages
        print(f"skip claimant tests: {e}")
        return

    def msg(t, ctx=None):
        return SimpleNamespace(msg_type=t, context=ctx or {}, data={})

    plugin = "ovos-common-reading-pipeline-plugin.andlo"
    recs = [msg("recognizer_loop:utterance"),
            msg(f"{plugin}:read_by_collection", {"skill_id": plugin}),
            msg("ovos.common_reading.search"),
            msg("ovos.common_reading.fetch_content.ovos-skill-grimm-tales.andlo"),
            msg("speak", {"skill_id": plugin})]
    who, fired = claimant(recs, {"ovos-skill-grimm-tales.andlo", "ovos-skill-weather.openvoiceos"})
    ok(who == "ovos-skill-grimm-tales.andlo" and fired == [], f"the provider asked for content ({who})")

    who, _ = claimant(recs, {"ovos-skill-andersen-tales.andlo"})
    ok(who is None, "another provider's row is not credited")

    recs2 = [msg("ovos-skill-weather.openvoiceos:current_weather"),
             msg("ovos.common_reading.fetch_content.ovos-skill-grimm-tales.andlo")]
    who, _ = claimant(recs2, {"ovos-skill-grimm-tales.andlo", "ovos-skill-weather.openvoiceos"})
    ok(who == "ovos-skill-weather.openvoiceos", "a fired intent still wins")


def test_companion_that_does_not_install():
    import run_shard
    provider = ({"id": "andlo-ovos-skill-grimm-tales"}, {"registrations": {"common_reading": ["x"]}})
    other = ({"id": "OpenVoiceOS-ovos-skill-weather"}, {"registrations": {"intents": ["y"]}, "routing": {"ref": "v1"}})
    spec = {"requirements": ["ovos-core[skills-essential]"], "pipeline": ["stop_high", "ovos-fallback-pipeline-plugin-low"]}
    seen = []

    def route(routable, all_runs, sp, field, *a):
        seen.append(list(sp["requirements"]))
        if "ovos-common-reading-pipeline-plugin" in sp["requirements"]:
            for _, r in routable:
                r.setdefault(field, {})["error"] = "the default skills did not install under the channel constraints: x"
            return None
        for _, r in routable:
            r.setdefault(field, {})["golden"] = {"status": "ok"}
        return {"boots": 1}

    out = run_shard.route_with_companions([provider, other], {}, spec, "routing", "route", None, None, 0,
                                          "the default skills", 30, route=route)
    ok(len(seen) == 2 and "ovos-common-reading-pipeline-plugin" not in seen[1], "retried without the companion")
    ok("did not install" in out.get("companion_pipelines_failed", ""), "the output says the companion failed")
    ok("error" not in other[1]["routing"] and other[1]["routing"].get("ref") == "v1", "the rest keeps a clean level 3")

    seen.clear()
    out = run_shard.route_with_companions([other], {}, spec, "routing", "route", None, None, 0,
                                          "the default skills", 30, route=route)
    ok(len(seen) == 1 and "companion_pipelines" not in out, "no provider in the shard: nothing added, no retry")


if __name__ == "__main__":
    test_companion_that_does_not_install()
    test_level2_records_providers()
    test_companions()
    test_claimant()
    print("\nALL OK" if not fails else f"\n{fails} FAILED")
    sys.exit(1 if fails else 0)
