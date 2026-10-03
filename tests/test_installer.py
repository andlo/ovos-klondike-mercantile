#!/usr/bin/env python3
"""What the OVOS installer installs is always tested (issue #54), without the network:

1. ovos-core[extra] expands through requires_dist, markers included
2. installer entries map to store entries, archived and odd types too
3. plan.py tests them (package, kind) and the Klondike job counts them
4. the profile overview splits Default/Extra by the installer and marks archived
5. the crawler reads OVOS's skill template setup.py (name=CONST, 'opm.skill')
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from compat.installer import entries, expand  # noqa: E402
from compat.plan import feed_map, klondike_items, package_of  # noqa: E402
from compat.profile_report import build  # noqa: E402
import generate_klondike_data as crawler  # noqa: E402

fails = 0


def ok(cond, what):
    global fails
    print(("ok   " if cond else "FAIL ") + what)
    fails += not cond


REQUIRES = [
    "requests<3",
    'ovos-skill-weather<2; extra == "skills-internet"',
    'ovos-skill-hello-world>=0.1; extra == "skills-essential"',
    'ovos-skill-randomness>=1; python_version >= "3.10" and extra == "skills-essential"',
    'ovos-skill-old; python_version < "3.8" and extra == "skills-essential"',
    'ovos-skill-news>=0.4; extra == "skills-media"',
    'ovos-persona<1; extra == "plugins"',
    'ovos-adapt-parser<2; extra == "plugins"',
    'ovos-translate-server-plugin; extra == "plugins"',
    'pytest; extra == "test"',
]
FEED = [
    {"id": "o-weather", "package_name": "ovos-skill-weather", "component_type": "Skill", "tier": 1,
     "source": "https://github.com/o/ovos-skill-weather"},
    {"id": "o-hello", "package_name": None, "component_type": "Infrastructure", "tier": None,
     "source": "https://github.com/o/ovos-skill-hello-world"},
    {"id": "o-random", "package_name": "ovos-skill-randomness", "component_type": "Skill", "tier": 1,
     "source": "https://github.com/o/ovos-skill-randomness"},
    {"id": "o-news", "package_name": "ovos-skill-news", "component_type": "Skill", "tier": 1, "archived": True,
     "source": "https://github.com/o/ovos-skill-news"},
    {"id": "o-persona", "package_name": "ovos-persona", "component_type": "Memory Plugin", "tier": 1,
     "source": "https://github.com/o/ovos-persona"},
    {"id": "o-adapt", "package_name": "ovos_adapt_parser", "component_type": "Pipeline Plugin", "tier": 1,
     "source": "https://github.com/o/ovos-adapt-pipeline-plugin"},
    {"id": "o-translate", "package_name": "ovos-translate-server-plugin", "component_type": "Other", "tier": 1,
     "source": "https://github.com/o/ovos-translate-server-plugin"},
]
PIPELINE = ["ovos-stop-pipeline-plugin-high", "ovos-persona-pipeline-plugin-high",
            "ovos-adapt-pipeline-plugin-high", "ovos-persona-pipeline-plugin-low"]
PREVIOUS = {"o-adapt": {"testing": {"kind": "pipeline", "plugin_ids": ["ovos-adapt-pipeline-plugin"]}}}


def test_expand():
    got = expand(["ovos-core[skills-essential,skills-internet]", "ovos-skill-jokes",
                  "git+https://github.com/x/y.git"], REQUIRES)
    ok(got == ["ovos-skill-weather", "ovos-skill-hello-world", "ovos-skill-randomness", "ovos-skill-jokes"],
       f"extras, markers and plain lines; git+ skipped ({got})")


def test_entries():
    m = entries(FEED, REQUIRES, ["ovos-core[skills-essential,skills-internet]"], ["ovos-core[skills-media]"],
                PIPELINE, PREVIOUS)
    ok(set(m) == {"o-weather", "o-hello", "o-random", "o-news", "o-persona", "o-adapt"},
       f"installer entries, not unused plugins ({sorted(m)})")
    ok(m["o-hello"] == {"package": "ovos-skill-hello-world", "kind": "skill", "profile": "default"},
       "an entry without a package name is found by its repo and gets the installer's package")
    ok(m["o-news"]["profile"] == "extra", "an archived extra skill is in the extra profile")
    ok(m["o-persona"]["kind"] == "pipeline", "a Memory Plugin whose stages the installer uses is a pipeline")
    ok(m["o-adapt"]["kind"] == "pipeline", "a pipeline found through its plugin ids from an earlier run")
    ok(entries(FEED, [], ["ovos-core[skills-essential]"], [], PIPELINE) == {},
       "no requires_dist (no PyPI): nothing extra, the store rule stands")
    return m


def test_plan(m):
    inst = {"testing": m}
    ok(package_of(FEED[1], inst) == "ovos-skill-hello-world", "package_of falls back to the installer's name")
    fmap = feed_map(FEED, m)
    ok("ovos-skill-news" in fmap and "ovos-skill-hello-world" in fmap,
       "the Klondike job counts archived / unnamed installer skills as store skills")
    ok("ovos-persona" not in fmap, "a pipeline plugin is not a skill in the feed map")
    prev = {"o-news": {"testing": {"status": "pass", "plugin_ids": ["ovos-skill-news.o"], "version_tested": "1"}},
            "o-hello": {"testing": {"status": "pass", "plugin_ids": ["ovos-skill-hello-world.o"],
                                    "version_tested": "2"}}}
    items = {i["id"]: i for i in klondike_items(FEED, prev, "testing", {}, m)}
    ok(set(items) == {"o-news", "o-hello"} and items["o-hello"]["package"] == "ovos-skill-hello-world",
       f"Klondike routes installer skills that passed level 2 ({sorted(items)})")


def test_profile_report():
    doc = {"generated_at": "t", "channels": {"testing": {"route": {
        "baseline_ids": ["ovos-skill-weather.o"], "pipeline_used": []}}},
        "results": {"o-weather": {"testing": {"plugin_ids": ["ovos-skill-weather.o"], "status": "pass", "level": 2,
                                              "kind": "skill"}},
                    "o-news": {"testing": {"plugin_ids": ["ovos-skill-news.o"], "status": "pass", "level": 2,
                                           "kind": "skill"}}},
        "installer": {"testing": {"o-hello": {"profile": "default", "kind": "skill"},
                                  "o-news": {"profile": "extra", "kind": "skill"}}},
        "klondike": {"testing": {"profile": {"skill_ids": ["ovos-skill-weather.o"], "curated": []},
                                 "job": {"results": {}}}}}
    out = build(doc, FEED)
    prof = {p["id"]: {e["store_id"]: e for e in p["entries"]} for p in out["channels"]["testing"]["profiles"]}
    ok(set(prof["default"]) == {"o-weather", "o-hello"}, f"Default from the installer + what booted ({sorted(prof['default'])})")
    ok(prof["default"]["o-hello"]["state"] == "untested", "an installer entry not yet tested shows as untested")
    ok(set(prof["extra"]) == {"o-news"} and prof["extra"]["o-news"].get("archived"),
       "an archived extra skill is listed and marked")


def test_crawler():
    setup = '''PYPI_NAME = "ovos-skill-hello-world"  # pip install PYPI_NAME
setup(
    name=PYPI_NAME,
    entry_points={'opm.skill': PLUGIN_ENTRY_POINT}
)'''
    ok(crawler.derive_package_name(setup, "") == "ovos-skill-hello-world", "setup(name=CONST) is resolved")
    ok(crawler.derive_component_type(crawler.derive_entry_point_groups(setup, "")) == "Skill",
       "a single-quoted 'opm.skill' entry point is read")
    ok(crawler.derive_package_name('setup(name="x-y")', "") == "x-y", "a literal name still works")


if __name__ == "__main__":
    test_expand()
    test_plan(test_entries())
    test_profile_report()
    test_crawler()
    print("\nALL OK" if not fails else f"\n{fails} FAILED")
    sys.exit(1 if fails else 0)
