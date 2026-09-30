"""Icon discovery in the crawler (resolve_icon). Run: python3 tests/test_icons.py"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import generate_klondike_data as g  # noqa: E402

REPO = "andlo/ovos-skill-x"


def no_tree(*a):
    raise AssertionError("the tree must not be fetched when skill.json or the README gave an icon")


def check(name, cond):
    print(("ok   " if cond else "FAIL ") + name)
    if not cond:
        raise SystemExit(1)


check("skill.json absolute URL is kept",
      g.resolve_icon(REPO, "main", "https://x.org/i.png", "", no_tree) == ("https://x.org/i.png", "skill.json", None))
check("skill.json relative path becomes a raw URL",
      g.resolve_icon(REPO, "dev", "./res/icon/x.svg", "", no_tree)[0]
      == "https://raw.githubusercontent.com/andlo/ovos-skill-x/dev/res/icon/x.svg")
check("a dot-folder survives", g.raw_url(REPO, "main", ".github/logo.png").endswith("/main/.github/logo.png"))

mycroft = "# <img src='https://raw.githack.com/FortAwesome/Font-Awesome/master/svgs/solid/bed.svg' card_color='#22a7f0' width='50' height='50' style='vertical-align:bottom'/> Naptime\n"
check("Mycroft README header icon, with its colour",
      g.resolve_icon(REPO, "main", None, mycroft, no_tree)[1:] == ("readme", "#22a7f0"))
badges = "# X\n![PyPI](https://img.shields.io/pypi/v/x)\n<img src='https://img.shields.io/badge/a-b-blue.svg'>\n"
check("badges are never icons", g.icon_from_readme(badges) == (None, None))
check("a bad colour is dropped",
      g.icon_from_readme("<img src='https://x.org/logo.png' card_color='red;background:url(x)'>") == ("https://x.org/logo.png", None))

top = {"res", "ovos_skill_x"}
check("icon.png at the root", g.icon_score("icon.png", top) is not None)
check("logo beats a deeper icon", g.icon_score("logo.svg", top) > g.icon_score("res/icon/stop.svg", top))
check("an image in a top-level icons/ folder counts", g.icon_score("icons/stop.png", top) is not None)
check("PrimaryLogo_Green.png counts", g.icon_score("PrimaryLogo_Green.png", top) is not None)
for bad in ("gui/qt5/nature.jpg", "docs/screenshot-icon.png", "test/icon.png", "gui.png", "icon.txt"):
    check(f"not an icon: {bad}", g.icon_score(bad, top) is None)

check("GUI icons are not the skill's icon",
      g.icon_score("ovos_PHAL_plugin_balena_wifi/gui/qt5/icons/check-circle.svg", top) is None
      and g.icon_score("gui/qt5/icons/alarmicon.svg", top) is None)
check("but a logo in the GUI folder is", g.icon_score("gui/all/logo.png", top) is not None)
check("a news source's logotype is not", g.icon_score("res/images/rg-logotipo-dark.svg", top) is None)
check("res/icon/ at the top counts", g.icon_score("res/icon/laugh_icon.png", top) is not None)
check("rawgithub.com Font Awesome is moved to jsDelivr (v5)",
      g.normalize_icon_url("https://rawgithub.com/FortAwesome/Font-Awesome/master/svgs/solid/sun.svg")
      == "https://cdn.jsdelivr.net/npm/@fortawesome/fontawesome-free@5/svgs/solid/sun.svg")
check("a 6.x branch keeps v6, a double slash is fine",
      g.normalize_icon_url("https://raw.githubusercontent.com/FortAwesome/Font-Awesome/6.x/svgs/solid//folder-open.svg")
      == "https://cdn.jsdelivr.net/npm/@fortawesome/fontawesome-free@6/svgs/solid/folder-open.svg")
check("other URLs are untouched", g.normalize_icon_url("https://x.org/icon.png") == "https://x.org/icon.png")
check("the README icon comes out normalized",
      g.resolve_icon(REPO, "main", None, mycroft, no_tree)[0]
      == "https://cdn.jsdelivr.net/npm/@fortawesome/fontawesome-free@5/svgs/solid/bed.svg")

news = [{"type": "blob", "path": f"res/images/{n}-logo.svg"} for n in ("sky-news", "bbc", "npr", "rg")]
check("a folder of many logos is content, not the icon", g.pick_icon_path(news, top) is None)
check("the root icon wins over them",
      g.pick_icon_path(news + [{"type": "blob", "path": "icon.png"}], top) == "icon.png")

check("a source logo deeper in the repo is not the icon", g.icon_score("res/images/sky-news-logo.svg", top) is None)

calls = []
check("the tree is the last resort",
      g.resolve_icon(REPO, "main", None, "# plain", lambda f, b: calls.append(1) or "https://t/icon.png")
      == ("https://t/icon.png", "repo", None) and calls == [1])
check("nothing found", g.resolve_icon(REPO, "main", "", "", lambda f, b: None) == (None, None, None))
print("\nALL OK")
