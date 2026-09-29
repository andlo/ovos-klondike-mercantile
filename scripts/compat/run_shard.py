#!/usr/bin/env python3
"""Test a shard of packages against one channel: level 1 (installs) and
level 2 (loads in MiniCroft).

Runs in the secret-less test job. Input is a JSON list of items from
plan.py; output is one JSON list of result records. Every package gets a
fresh copy of the channel base venv, so one skill's dependencies can never
change what the next skill is tested against.

Result status:
  pass   the level was reached
  unsupported  the channel cannot run this kind of package at all (stable's
         ovos-core has no third-party pipeline plugin loader): not the
         package's fault, shown as "not supported", never as a failure
  needs_device  loading blocks in the package's own code waiting for
         something only a device provides (network/GUI ready signals);
         shown as "needs device" with the file:line, never as a failure
  fail   the package's own fault (dependency conflict, import error, boot
         error, timeout while booting)
  error  our/infra fault (PyPI unreachable, disk full): not published as a
         failure, and retried on the next run
"""
import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
PROBE = HERE / "probe.py"
ANSI = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")
NETWORK_ERRORS = re.compile(
    r"(ConnectionError|ReadTimeout|Max retries exceeded|Temporary failure in name "
    r"resolution|No space left on device|HTTP error 5\d\d|403 Client Error)")
MAX_EXCERPT = 4000


def excerpt(text, anchor_patterns=("Traceback (most recent call last)", "ERROR", "error:")):
    """The most useful tail of a log: from the last traceback/error on."""
    text = ANSI.sub("", text or "")
    lines = text.splitlines()
    start = max(0, len(lines) - 40)
    for i in range(len(lines) - 1, -1, -1):
        if any(p in lines[i] for p in anchor_patterns):
            start = max(0, i - 5)
            break
    out = "\n".join(lines[start:start + 60])
    return out[-MAX_EXCERPT:]


def pip_reason(output):
    for pat in ("ResolutionImpossible", "Cannot install", "conflict is caused by",
                "No matching distribution found", "Could not find a version",
                "Failed building wheel", "subprocess-exited-with-error"):
        for line in output.splitlines():
            if pat in line:
                return line.strip()[:300]
    return "pip install failed"


def run(cmd, timeout, log_path):
    with open(log_path, "w") as log:
        try:
            proc = subprocess.run(cmd, stdout=log, stderr=subprocess.STDOUT,
                                  timeout=timeout, env={**os.environ, "PIP_NO_INPUT": "1"})
            rc = proc.returncode
        except subprocess.TimeoutExpired:
            rc = None
    return rc, Path(log_path).read_text(errors="replace")


def test_item(item, args, workroot):
    started = time.monotonic()
    rec = {
        "id": item["id"], "channel": args.channel, "key": item["key"],
        "kind": item["kind"], "package": item["package"],
        "requested_version": item.get("version"), "channel_pinned": item.get("channel_pinned", False),
        "tested_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "level": 0,
    }
    venv = Path(workroot) / "venv"
    if venv.exists():
        shutil.rmtree(venv)
    try:
        shutil.copytree(args.base_venv, venv, symlinks=True)
    except OSError as e:
        rec.update(status="error", stage="setup", reason=f"could not copy base venv: {e}")
        return rec
    py = str(venv / "bin" / "python")
    try:
        # Level 1. A channel that pins the package decides its version (what
        # a device on that channel actually runs); otherwise the latest
        # release, still under the channel constraints.
        spec = item["package"] if item.get("channel_pinned") or not item.get("version") \
            else f"{item['package']}=={item['version']}"
        rc, out = run([py, "-m", "pip", "install", "--disable-pip-version-check",
                       "-c", args.constraints, spec],
                      args.install_timeout, Path(workroot) / "install.log")
        if rc != 0:
            if rc is None:
                rec.update(status="error", stage="install",
                           reason=f"pip install timed out after {args.install_timeout}s")
            elif NETWORK_ERRORS.search(out):
                rec.update(status="error", stage="install", reason="network error during pip install")
            else:
                rec.update(status="fail", stage="install", reason=pip_reason(out))
            rec["log_excerpt"] = excerpt(out, ("ERROR", "error:", "conflict"))
            return rec
        rec["level"] = 1

        # Level 2
        result_path = Path(workroot) / "probe.json"
        if result_path.exists():
            result_path.unlink()
        rc, out = run([py, str(PROBE), "--kind", item["kind"], "--package", item["package"],
                       "--langs", ",".join(item.get("languages") or []),
                       "--out", str(result_path), "--max-wait", str(args.boot_timeout)],
                      args.boot_timeout + 120, Path(workroot) / "probe.log")
        if not result_path.exists():
            reason = (f"timed out booting after {args.boot_timeout + 120}s" if rc is None
                      else f"probe crashed (exit {rc})")
            rec.update(status="fail", stage="load", reason=reason, log_excerpt=excerpt(out))
            return rec
        probe = json.loads(result_path.read_text())
        rec["version_tested"] = probe.get("version_installed")
        for k in ("plugin_ids", "registrations", "intents_by_lang", "languages_booted",
                  "languages_missing", "warnings", "stages", "boot_seconds", "driver"):
            if probe.get(k) not in (None, [], {}):
                rec[k] = probe[k]
        if probe.get("status") in ("unsupported", "needs_device"):
            rec.update(status=probe["status"], stage="load", reason=probe.get("reason", ""),
                       log_excerpt=excerpt(out))
        elif probe.get("status") == "pass":
            rec.update(status="pass", stage="load", level=2)
            if rec.get("warnings"):
                rec["log_excerpt"] = excerpt(out)
        else:
            rec.update(status="fail", stage="load", reason=probe.get("reason", "did not load"),
                       log_excerpt=excerpt(out))
        return rec
    finally:
        rec["duration_seconds"] = round(time.monotonic() - started, 1)
        shutil.rmtree(venv, ignore_errors=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--channel", required=True)
    ap.add_argument("--constraints", required=True)
    ap.add_argument("--base-venv", required=True)
    ap.add_argument("--items", required=True, help="JSON list from plan.py")
    ap.add_argument("--out", required=True)
    ap.add_argument("--install-timeout", type=int, default=900)
    # Generous: a skill with ~20 languages trains ~20 padatious containers
    # before READY (~200s locally, slower on a 2-core hosted runner). A
    # boot that exceeds this is reported as a failure, so it must not be
    # tight enough to catch merely slow-but-correct skills.
    ap.add_argument("--boot-timeout", type=int, default=900)
    args = ap.parse_args()

    items = json.loads(Path(args.items).read_text())
    results = []
    with tempfile.TemporaryDirectory(prefix="compat-") as workroot:
        # Canary: an empty MiniCroft on the untouched base venv. If the test
        # driver itself cannot boot on this channel, no package is to blame,
        # so every item becomes "error" (retried, never published as a ✗).
        canary_out = Path(workroot) / "canary.json"
        rc, out = run([str(Path(args.base_venv) / "bin" / "python"), str(PROBE), "--kind", "canary",
                       "--out", str(canary_out), "--max-wait", str(args.boot_timeout)],
                      args.boot_timeout + 120, Path(workroot) / "canary.log")
        canary = json.loads(canary_out.read_text()) if canary_out.exists() else \
            {"status": "fail", "reason": "canary timed out" if rc is None else f"canary crashed (exit {rc})"}
        Path(args.out).with_name("canary.json").write_text(
            json.dumps({**canary, "log_excerpt": excerpt(out) if canary.get("status") != "pass" else ""}, indent=2))
        print(f"==> canary: {canary.get('status')} {canary.get('reason', '')} "
              f"driver={canary.get('driver')}", flush=True)
        if canary.get("status") != "pass":
            now = datetime.now(timezone.utc).isoformat(timespec="seconds")
            for item in items:
                results.append({"id": item["id"], "channel": args.channel, "key": item["key"],
                                "kind": item["kind"], "package": item["package"],
                                "requested_version": item.get("version"), "tested_at": now,
                                "level": 0, "status": "error", "stage": "setup",
                                "reason": "test driver cannot boot on this channel: "
                                          + str(canary.get("reason", ""))[:300]})
            Path(args.out).write_text(json.dumps(results, indent=2))
            return 0

        for n, item in enumerate(items, 1):
            print(f"==> [{n}/{len(items)}] {args.channel} {item['kind']} {item['package']} "
                  f"{item.get('version') or '(channel pin)'}", flush=True)
            rec = test_item(item, args, workroot)
            print(f"    {rec['status']} level={rec['level']} {rec.get('reason', '')} "
                  f"({rec['duration_seconds']}s)", flush=True)
            results.append(rec)
            # Written after every item, so a job killed by its time limit
            # still uploads what it finished.
            Path(args.out).write_text(json.dumps(results, indent=2))
    Path(args.out).write_text(json.dumps(results, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
