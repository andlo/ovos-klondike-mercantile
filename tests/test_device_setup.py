#!/usr/bin/env python3
"""device_setup.sh builds a device's channel stack the way the store does,
checked without a device, OVOS or the network:

1. it locks exactly run_shard.py's LOCKED_STACK
2. no pip call takes pre-releases wholesale (--pre), so a third-party dev
   release (httpx 1.0.devN) can only come in when a requirement names one
3. every install after the stack carries the channel constraints and the lock
4. the harness's test tooling is kept off the device
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts" / "compat"))

import run_shard  # noqa: E402

SCRIPT = (ROOT / "scripts" / "compat" / "device_setup.sh").read_text()
fails = 0


def ok(cond, what):
    global fails
    print(("ok   " if cond else "FAIL ") + what)
    fails += not cond


def test_lock_matches_store():
    m = re.search(r'for p in \(([^)]*)\):', SCRIPT)
    locked = tuple(re.findall(r'"([^"]+)"', m.group(1))) if m else ()
    ok(set(locked) == set(run_shard.LOCKED_STACK),
       f"device lock {sorted(locked)} == run_shard.LOCKED_STACK")


def test_no_pre():
    ok("--pre" not in SCRIPT.replace("no --pre", "").replace("without --pre", ""),
       "no pip call uses --pre")


def test_later_installs_locked():
    installs = [l for l in SCRIPT.splitlines()
                if '"${PIP[@]}"' in l and "stack.txt" not in l and not l.lstrip().startswith("#")]
    ok(installs and all("-c constraints.txt -c lock.txt" in l for l in installs),
       f"every install after the stack uses the constraints and the lock ({len(installs)} calls)")


def test_test_tools_excluded():
    ok("TEST_TOOLS" in SCRIPT and "ovoscope" in SCRIPT.split("TEST_TOOLS =", 1)[1].splitlines()[0],
       "ovoscope (the harness's test driver) is kept off the device")


if __name__ == "__main__":
    test_lock_matches_store()
    test_no_pre()
    test_later_installs_locked()
    test_test_tools_excluded()
    print("\nALL OK" if not fails else f"\n{fails} FAILED")
    sys.exit(1 if fails else 0)
