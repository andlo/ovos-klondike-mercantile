#!/usr/bin/env python3
"""Which locale/ folder names the crawler accepts as languages.

Three-letter ISO 639-3 codes such as "kab" (Kabyle) are real OVOS
locales and must not be dropped; other folders that can sit next to
the language folders must still be ignored.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from generate_klondike_data import LOCALE_DIR_PATTERN  # noqa: E402

fails = 0


def ok(cond, what):
    global fails
    print(("ok   " if cond else "FAIL ") + what)
    fails += not cond


def test_accepts_real_locale_folders():
    for name in ("da-DK", "en-US", "da", "kab", "kab-DZ", "eu-ES", "es-lm", "ar-xa"):
        ok(bool(LOCALE_DIR_PATTERN.match(name)), f"{name} is a language folder")


def test_ignores_non_locale_folders():
    for name in ("README", "vocab", "dialog", "x", "abcd", "da_DK", "da-"):
        ok(not LOCALE_DIR_PATTERN.match(name), f"{name} is not a language folder")


if __name__ == "__main__":
    test_accepts_real_locale_folders()
    test_ignores_non_locale_folders()
    print("\nALL OK" if not fails else f"\n{fails} FAILED")
    sys.exit(1 if fails else 0)
