"""The test key's stack part (issue #39). Run: python3 tests/test_stack_key.py"""
import sys
from pathlib import Path

from packaging.version import Version

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from compat.plan import (effective_stack, resolve_channel_version, stack_moves,  # noqa: E402
                         stack_signature)

fails = 0


def ok(cond, name):
    global fails
    print(("ok   " if cond else "FAIL ") + name)
    fails += 0 if cond else 1


def rel(*vs):
    return sorted(Version(v) for v in vs)


CORE = rel("1.3.1", "2.1.1", "2.2.4a1", "3.7.1a3")
RELEASES = {
    "ovos-core": CORE,
    "ovos-workshop": rel("0.1.9", "7.4.1", "8.3.0a1", "9.8.9a2"),
    "ovos-utils": rel("0.8.5", "0.15.4a2"),
    "ovos-padatious": rel("1.4.2", "2.2.7a1"),
}
ALPHA = {"ovos-core": ">=2.2.4a1", "ovos-workshop": ">=8.3.0a1", "ovos-padatious": ">=2.2.7a1",
         "ovos-skill-foo": ">=0.1.0a1"}
TESTING = {"ovos-core": ">=2.1.1,<3.0.0", "ovos-workshop": ">=7.0.0,<8.0.0"}


def test_resolve():
    ok(resolve_channel_version(CORE, ">=2.2.4a1", "alpha") == "3.7.1a3", "alpha: newest pre-release over the floor")
    ok(resolve_channel_version(CORE, ">=2.1.1,<3.0.0", "testing") == "2.1.1", "testing: newest in its range")
    ok(resolve_channel_version(CORE, "", "stable") == "2.1.1", "unpinned on stable: newest final")
    ok(resolve_channel_version(rel("0.8.5", "0.15.4a2"), "", "alpha") == "0.15.4a2", "unpinned on alpha: newest, pre included")


def test_signature():
    base = stack_signature(effective_stack(ALPHA, "alpha", RELEASES), "sha-a")
    other_line = dict(ALPHA, **{"ovos-skill-foo": ">=0.2.0a1"})
    ok(stack_signature(effective_stack(other_line, "alpha", RELEASES), "sha-b") == base,
       "a constraints line for an unrelated package changes nothing")

    newer = dict(RELEASES, **{"ovos-core": rel("1.3.1", "2.1.1", "2.2.4a1", "3.7.1a3", "3.7.2a1")})
    ok(stack_signature(effective_stack(ALPHA, "alpha", newer), "sha-a") != base,
       "a new ovos-core pre-release re-tests alpha, with the file unchanged")

    patch = dict(RELEASES, **{"ovos-utils": rel("0.8.5", "0.15.4a2", "0.15.4a3")})
    ok(stack_signature(effective_stack(ALPHA, "alpha", patch), "sha-a") == base,
       "a patch release of a utility doesn't")
    minor = dict(RELEASES, **{"ovos-utils": rel("0.8.5", "0.15.4a2", "0.16.0a1")})
    ok(stack_signature(effective_stack(ALPHA, "alpha", minor), "sha-a") != base, "a minor release does")

    t = stack_signature(effective_stack(TESTING, "testing", newer), "sha-t")
    ok(t == stack_signature(effective_stack(TESTING, "testing", RELEASES), "sha-t"),
       "testing ignores an alpha pre-release outside its range")

    ok(stack_signature(effective_stack(ALPHA, "alpha", {}), "sha-a") == {"constraints_sha256": "sha-a"},
       "no PyPI: falls back to the constraints file")


def test_moves():
    old = effective_stack(ALPHA, "alpha", RELEASES)
    new = effective_stack(ALPHA, "alpha", dict(RELEASES, **{"ovos-core": rel("3.7.1a3", "3.7.2a1")}))
    ok(stack_moves(old, new) == ["ovos-core 3.7.1a3 -> 3.7.2a1"], "the plan says which package moved")
    ok(stack_moves(old, old) == [], "nothing moved")


if __name__ == "__main__":
    test_resolve()
    test_signature()
    test_moves()
    print("\nALL OK" if not fails else f"\n{fails} FAILED")
    sys.exit(1 if fails else 0)
