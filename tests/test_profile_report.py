#!/usr/bin/env python3
"""The profile report (Default / + Extra / + Klondike), without the network:

1. runtime ids map to store ids through the results, then skills.json
2. each entry lands in exactly one profile, and stages map to their plugin
3. a curated entry left out on a channel is shown, but not counted
4. the output matches docs/schemas/ovos-profile-report-1.json (if jsonschema is installed)
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from compat.profile_report import build  # noqa: E402

fails = 0


def ok(cond, what):
    global fails
    print(("ok   " if cond else "FAIL ") + what)
    fails += not cond


def rec(plugin_id, level=2, status="pass", kind="skill", golden=None):
    r = {"plugin_ids": [plugin_id], "level": level, "status": status, "kind": kind, "version_tested": "1.0.0"}
    if golden:
        r["routing"] = {"golden": {"status": "ok", "hit": golden[0], "counted": golden[1]}}
    return r


DOC = {
    "generated_at": "2026-10-03T00:00:00+00:00",
    "channels": {"testing": {"route": {
        "baseline_ids": ["weather.ovos", "hello.ovos", "untested.ovos"],
        "pipeline_used": ["stop-pipeline-plugin-high", "padatious-pipeline-plugin-high", "reading-pipeline-plugin-high"],
    }}},
    "results": {
        "o-weather": {"testing": rec("weather.ovos", 3, golden=(10, 10))},
        "o-core": {"testing": rec("stop-pipeline-plugin", kind="pipeline")},
        "o-padatious": {"testing": rec("padatious-pipeline-plugin", 1, "fail", kind="pipeline")},
        "o-jokes": {"testing": rec("jokes.ovos")},
        "a-calc": {"testing": rec("calc.andlo", 3, golden=(5, 5))},
        "a-broken": {"testing": rec("broken.andlo", 1, "fail")},
        "a-reading": {"testing": rec("reading-pipeline-plugin", kind="pipeline")},
    },
    "klondike": {"testing": {
        "profile": {
            "skill_ids": ["weather.ovos", "hello.ovos", "untested.ovos", "jokes.ovos", "calc.andlo"],
            "curated": [{"id": "a-calc", "in": True, "function": "arithmetic"},
                        {"id": "a-broken", "in": False, "function": "broken"}],
            "left_out": {"a-broken": "level 2 on testing: fail"},
            "added_stages": ["reading-pipeline-plugin-high"],
            "extra_requirements": ["jokes"],
        },
        "job": {"run_at": "x", "results": {
            "o-weather": {"routing": {"golden": {"status": "ok", "hit": 9, "counted": 10}}},
            "a-calc": {"routing": {"golden": {"status": "ok", "hit": 2, "counted": 4}}},
        }},
    }},
}
SKILLS = [{"id": "o-untested", "skill_id": "untested.ovos", "package_name": "untested"}]


def entries(out, pid):
    prof = next(p for p in out["channels"]["testing"]["profiles"] if p["id"] == pid)
    return prof, {e["store_id"] or e["runtime_id"]: e for e in prof["entries"]}


def test_report():
    out = build(DOC, SKILLS)
    ok(out["schema"] == "ovos-profile-report/1" and out["generated_at"] == DOC["generated_at"],
       "stamped with the results' time, so an unchanged run writes the same file")
    prof, d = entries(out, "default")
    ok(set(d) == {"o-weather", "hello.ovos", "o-untested", "o-core", "o-padatious"},
       f"default: baseline skills and the installer's pipeline, not the added stage ({sorted(d)})")
    ok(d["hello.ovos"]["state"] == "not_in_store", "a default skill the store lacks is not_in_store")
    ok(d["o-untested"]["state"] == "untested", "found through skills.json: in the store, untested")
    ok(d["o-padatious"]["kind"] == "pipeline" and d["o-padatious"]["state"] == "fail", "a stage maps to its plugin")
    ok(d["o-weather"]["gold"] and d["o-weather"]["klondike"] == {"hit": 9, "counted": 10}, "level 3 + Klondike 9/10 is gold")
    ok(prof["summary"]["loads"] == 2 and prof["summary"]["fails"] == 1, f"default summary ({prof['summary']})")
    _, d = entries(out, "extra")
    ok(set(d) == {"o-jokes"}, f"extra: profile skills minus default and curated ({sorted(d)})")
    prof, d = entries(out, "klondike")
    ok(set(d) == {"a-calc", "a-broken", "a-reading"}, f"klondike: curated + added pipeline ({sorted(d)})")
    ok(not d["a-calc"]["gold"], "Klondike 2/4 is not gold")
    ok(d["a-broken"]["in_profile"] is False and "left out" in d["a-broken"]["note"], "a left-out entry says why")
    ok(prof["cumulative"]["total"] == 5 + 1 + 2, f"cumulative skips the left-out entry ({prof['cumulative']['total']})")
    try:
        import jsonschema
    except ImportError:
        print("skip schema check: jsonschema not installed")
        return
    schema = json.loads((ROOT / "docs/schemas/ovos-profile-report-1.json").read_text())
    try:
        jsonschema.validate(out, schema)
        ok(True, "matches the schema")
    except jsonschema.ValidationError as e:
        ok(False, f"matches the schema: {e.message}")


if __name__ == "__main__":
    test_report()
    print("\nALL OK" if not fails else f"\n{fails} FAILED")
    sys.exit(1 if fails else 0)
