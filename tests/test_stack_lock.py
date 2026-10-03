#!/usr/bin/env python3
"""The channel's OVOS stack is locked in every install, without OVOS or the network:

1. write_stack_lock pins the base venv's stack packages, nothing else
2. every pip install carries the channel constraints and the lock
3. a package under test that is part of the stack is left out of its own lock
4. only the packages that define the channel are locked (not the intent engines)
"""
import sys
import tempfile
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts" / "compat"))

import run_shard  # noqa: E402

fails = 0


def ok(cond, what):
    global fails
    print(("ok   " if cond else "FAIL ") + what)
    fails += not cond


def test_lock():
    with tempfile.TemporaryDirectory() as d:
        lock = Path(d) / "stack-lock.txt"
        # this interpreter stands in for the base venv: whatever it has of
        # the stack is locked, and nothing outside LOCKED_STACK
        locked = run_shard.write_stack_lock(sys.executable, lock)
        lines = [l for l in lock.read_text().splitlines() if l]
        ok(all(l.split("==")[0] in run_shard.LOCKED_STACK for l in lines), "only stack packages are locked")
        ok(len(lines) == len(locked), "the file says what was locked")

        args = types.SimpleNamespace(constraints="/c/constraints-alpha.txt", stack_lock=str(lock),
                                     stack_locked={"ovos-core": "3.7.2a2", "ovos-workshop": "9.8.11a1"})
        lock.write_text("ovos-core==3.7.2a2\novos-workshop==9.8.11a1\n")
        cmd = run_shard.pip_install_cmd("py", args, ["ovos-skill-pokepedia"])
        ok(cmd[-4:] == ["-c", "/c/constraints-alpha.txt", "-c", str(lock)],
           f"a skill installs under the channel constraints and the lock ({cmd[-4:]})")
        cmd = run_shard.pip_install_cmd("py", args, ["ovos_workshop"])
        own = Path(cmd[-1]).read_text()
        ok(cmd[-1] != str(lock) and "ovos-workshop" not in own and "ovos-core==3.7.2a2" in own,
           "a stack package under test is left out of its own lock, the rest stays locked")
        args.stack_lock = None
        ok(run_shard.pip_install_cmd("py", args)[-2:] == ["-c", "/c/constraints-alpha.txt"],
           "without a lock: the channel constraints only")


def test_scope():
    ok("padacioso" not in run_shard.LOCKED_STACK and "ovos-padatious" not in run_shard.LOCKED_STACK,
       "intent engines are not locked (the harness may install them from git)")
    ok({"ovos-core", "ovos-workshop"} <= set(run_shard.LOCKED_STACK), "ovos-core and ovos-workshop are")


if __name__ == "__main__":
    test_lock()
    test_scope()
    print("\nALL OK" if not fails else f"\n{fails} FAILED")
    sys.exit(1 if fails else 0)
