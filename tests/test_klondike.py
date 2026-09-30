#!/usr/bin/env python3
"""The Klondike profile (issue #13), without the network:

1. the TOML in the repo reads, and stages go where they are declared
2. which curated entries are in the profile on a channel, and the key
3. a report from a device matches the profile, or says why not
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from compat.baseline import insert_stages, read_profile  # noqa: E402
from compat.plan import channel_profile  # noqa: E402
from reports.validate import klondike_match  # noqa: E402

INSTALLER = ["ovos-stop-pipeline-plugin-high", "ovos-converse-pipeline-plugin",
             "ovos-padatious-pipeline-plugin-high", "ovos-fallback-pipeline-plugin-low"]
fails = 0


def ok(cond, what):
    global fails
    print(("ok   " if cond else "FAIL ") + what)
    fails += not cond


def test_profile_file():
    prof = read_profile(ROOT)
    ids = [s["id"] for s in prof["skills"]]
    ok(len(ids) == len(set(ids)) and len(ids) >= 10, f"profile TOML reads ({len(ids)} curated skills)")
    ok(any(p["stage"] == "ovos-common-reading-pipeline-plugin" for p in prof["pipeline"]),
       "the reading pipeline is in the profile")


def test_insert_stages():
    plug = [{"id": "x", "stage": "reading", "after": "ovos-stop-pipeline-plugin-high"}]
    out, added, skipped = insert_stages(INSTALLER, plug)
    ok(out[1] == "reading" and added == ["reading"], "a stage goes right after its anchor")
    out, _, _ = insert_stages(INSTALLER, [{"id": "x", "stage": "reading", "after": "stop_high"}])
    ok(out[1] == "reading", "a legacy anchor name (stop_high) is understood")
    out, _, _ = insert_stages(INSTALLER, [{"id": "x", "stage": "r", "before": "ovos-fallback-pipeline-plugin-low"}])
    ok(out[-2] == "r", "before works too")
    out, added, skipped = insert_stages(INSTALLER + ["reading"], plug)
    ok(out.count("reading") == 1 and not added and "reading" in skipped,
       "a stage the installer already has is not added twice")
    out, added, skipped = insert_stages(INSTALLER, [{"id": "x", "stage": "r", "after": "nope"}])
    ok(out == INSTALLER and "r" in skipped, "an unknown anchor leaves the stage out, with a reason")


def test_membership():
    baseline = {"requirements": ["ovos-core[skills-essential]"], "pipeline": INSTALLER}
    pdef = {"extra_requirements": ["ovos-core[skills-media]"],
            "curated": {"skills": [{"id": "a"}, {"id": "b"}, {"id": "c"}],
                        "pipeline": [{"id": "p", "stage": "reading", "after": "ovos-stop-pipeline-plugin-high"}]}}
    feed = {i: {"id": i, "package_name": f"pkg-{i}"} for i in ("a", "b", "p")}
    prev = {"a": {"testing": {"status": "pass"}}, "b": {"testing": {"status": "fail"}},
            "p": {"testing": {"status": "pass"}}}
    from packaging.version import Version
    rel = {i: [Version("1.0.0"), Version("1.1.0")] for i in feed}
    spec = channel_profile(pdef, baseline, "testing", feed, prev, {"pkg-a": "==1.0.0"}, rel)
    ok(spec["curated_members"] == ["a", "p"], "only entries that pass level 2 on the channel are in")
    ok(spec["left_out"] == {"b": "level 2 on testing: fail", "c": "not in the store"}, "left-out reasons")
    ok("pkg-a" in spec["requirements"] and "pkg-p==1.1.0" in spec["requirements"],
       "a pinned package follows the constraints, an unpinned one gets its resolved version")
    ok(spec["pipeline"][1] == "reading" and spec["added_stages"] == ["reading"], "member plugin's stage added")
    prev["p"]["testing"]["status"] = "fail"
    spec2 = channel_profile(pdef, baseline, "testing", feed, prev, {"pkg-a": "==1.0.0"}, rel)
    ok("reading" not in spec2["pipeline"] and spec2["sha256"] != spec["sha256"],
       "a plugin that fails is not in the pipeline, and the key changes")
    rel2 = {i: [Version("1.0.0"), Version("1.2.0")] for i in feed}
    prev["p"]["testing"]["status"] = "pass"
    spec3 = channel_profile(pdef, baseline, "testing", feed, prev, {"pkg-a": "==1.0.0"}, rel2)
    ok(spec3["sha256"] == spec["sha256"], "a new release of a profile skill alone does not change the key")


def report(installed, pipeline):
    return {"manifest": {"installed": installed, "config": {"pipeline": pipeline}}}


def test_match():
    prof = {"skill_ids": ["a.x", "b.x"], "stages": [{"stage": "reading", "after": "stop"}]}
    good = report([{"id": "a.x", "active": True}, {"id": "b.x"}, {"id": "c.x"}], ["stop", "reading", "adapt"])
    ok(klondike_match(good, prof) == (True, ""), "a device with the profile matches")
    m, why = klondike_match(report([{"id": "a.x"}, {"id": "b.x", "active": False}], ["stop", "reading"]), prof)
    ok(not m and why == "1 profile skill missing: b.x", f"an inactive profile skill is missing ({why})")
    m, why = klondike_match(report([{"id": "a.x"}, {"id": "b.x"}], ["reading", "stop"]), prof)
    ok(not m and "not after stop" in why, f"a stage in the wrong place ({why})")
    m, why = klondike_match(report([{"id": "a.x"}, {"id": "b.x"}], ["stop"]), prof)
    ok(not m and "no reading" in why, f"a stage missing ({why})")
    m, why = klondike_match({"manifest": {}}, prof)
    ok(not m and "0.2.0" in why, "an older report without manifest.installed says what is needed")


if __name__ == "__main__":
    test_profile_file()
    test_insert_stages()
    test_membership()
    test_match()
    print("\nALL OK" if not fails else f"\n{fails} FAILED")
    sys.exit(1 if fails else 0)
