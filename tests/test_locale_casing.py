#!/usr/bin/env python3
"""Translated skill.json is fetched by the locale folder's real spelling.

Language codes are lowercased for display (da-DK -> da-dk), but GitHub
paths are case-sensitive. Fetching locale/da-dk/skill.json from a repo
whose folder is da-DK is a 404, which left most OpenVoiceOS skills with
no translated name/description/examples in the store.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import generate_klondike_data as g  # noqa: E402

fails = 0


def ok(cond, what):
    global fails
    print(("ok   " if cond else "FAIL ") + what)
    fails += not cond


def test_languages_keep_real_folder_names():
    listing = [{"name": n, "type": "dir"} for n in ("da-DK", "en-US", "kab", "pt-br")]
    listing.append({"name": "README.md", "type": "file"})
    g.gh_ok = lambda *a, **k: listing
    languages, prefix, dirs = g.fetch_locale_languages("x/y")
    ok(languages == ["da-dk", "en-us", "kab", "pt-br"], f"codes lowercased: {languages}")
    ok(prefix == "", "root prefix")
    ok(dirs["da-dk"] == "da-DK" and dirs["kab"] == "kab", f"real names kept: {dirs}")


def test_content_fetched_by_real_name():
    asked = []

    def fake_fetch(full_name, locale, prefix=""):
        asked.append(locale)
        return {"name": "Navn"} if locale == "da-DK" else None

    g.fetch_skill_json_for_locale = fake_fetch
    content = g.fetch_locale_content("x/y", ["da-dk", "en-us"], "", {"da-dk": "da-DK", "en-us": "en-US"})
    ok(asked == ["da-DK"], f"asked for the real folder, English skipped: {asked}")
    ok(content == {"da-dk": {"name": "Navn"}}, f"keyed by lowercased code: {content}")


def test_no_locale_dir():
    g.gh_ok = lambda *a, **k: None
    g.find_locale_prefix_via_tree = lambda *a, **k: None
    ok(g.fetch_locale_languages("x/y") == ([], None, {}), "no locale/ -> empty triple")


if __name__ == "__main__":
    test_languages_keep_real_folder_names()
    test_content_fetched_by_real_name()
    test_no_locale_dir()
    sys.exit(1 if fails else 0)
