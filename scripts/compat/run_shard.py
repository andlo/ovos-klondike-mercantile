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
  needs_config  its own load error says it needs configuration first (an
         API key, account or identity): "needs config", with the message
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

# "Needs config" (issue #6): a package that cannot start until the user
# configures it (API key, account, identity) is not broken. Only the
# package's OWN load error is matched (a pipeline load error naming one of
# its ids, or a traceback running through its own modules), and only
# against phrases that say something is missing or unset, so a real bug
# stays a failure.
NEEDS_CONFIG = re.compile(
    r"(api[ _-]?key|token|credential|password|secret|identity|account|"
    r"not (?:set|configured)|please (?:pass|set|configure)|missing (?:config|setting)|"
    r"no .* configured)", re.I)
EXC_LINE = re.compile(r"^(?:\w+\.)*\w*(?:Error|Exception): (?P<msg>.+)$")


def config_message(output, plugin_ids, module_roots):
    """The package's own load error when it says configuration is missing."""
    text = ANSI.sub("", output or "")
    for pid in plugin_ids or []:
        m = re.search(rf"Failed to load pipeline plugin '{re.escape(pid)}': (?P<msg>.+)$", text, re.M)
        if m and NEEDS_CONFIG.search(m.group("msg")):
            return m.group("msg").strip()[:300]
    markers = [f"/site-packages/{r}/" for r in module_roots or []]
    for block in text.split("Traceback (most recent call last)")[1:]:
        lines = block.splitlines()
        if not any(any(mk in l for mk in markers) for l in lines):
            continue
        for l in lines:
            m = EXC_LINE.match(l.strip())
            if m and NEEDS_CONFIG.search(m.group("msg")):
                return m.group("msg").strip()[:300]
    return None


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
    """One line saying WHY pip gave up, e.g. "neon-skill-about 1.0.4 depends
    on ovos-workshop~=0.0; channel pins ovos-workshop<3.5.0,>=3.4.0"."""
    lines = [l.strip() for l in ANSI.sub("", output).splitlines()]
    if "The conflict is caused by:" in lines:
        i = lines.index("The conflict is caused by:")
        block = []
        for l in lines[i + 1:]:
            if not l or l.startswith(("Additionally", "To fix")):
                break
            block.append(l.replace("The user requested (constraint)", "channel pins"))
        if block:
            return "; ".join(dict.fromkeys(block))[:500]
    for pat in ("Failed to build", "No matching distribution found", "Could not find a version",
                "Cannot install", "subprocess-exited-with-error"):
        for l in lines:
            if pat in l:
                return l.removeprefix("ERROR: ")[:300]
    return "pip install failed"


def install_excerpt(output):
    text = ANSI.sub("", output)
    for anchor in ("The conflict is caused by:", "Getting requirements to build wheel", "ERROR:"):
        i = text.find(anchor)
        if i >= 0:
            return text[max(0, i - 400):][:MAX_EXCERPT]
    return excerpt(output)


# Intent training. ovoscope's defaults (180s of silence, 600s in total)
# suit a single-language CI boot; a skill booted with ~20 languages trains
# ~20 padatious containers, which took 220s alone on 8 cores and over 600s
# under load (ovos-skill-alerts). A hosted runner has 2 cores. Training that
# still has not finished after this is reported as a failure.
TRAINED_TIMEOUT = 600
TRAINED_MAX = 1800
PROBE_ENV = {"PIP_NO_INPUT": "1", "OVOSCOPE_TRAINED_TIMEOUT": str(TRAINED_TIMEOUT),
             "OVOSCOPE_TRAINED_MAX": str(TRAINED_MAX)}


def run(cmd, timeout, log_path):
    with open(log_path, "w") as log:
        try:
            proc = subprocess.run(cmd, stdout=log, stderr=subprocess.STDOUT,
                                  timeout=timeout, env={**os.environ, **PROBE_ENV})
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
            rec["log_excerpt"] = install_excerpt(out)
            return rec
        rec["level"] = 1

        # Level 2
        def probe_once(only_langs=""):
            result_path = Path(workroot) / "probe.json"
            if result_path.exists():
                result_path.unlink()
            cmd = [py, str(PROBE), "--kind", item["kind"], "--package", item["package"],
                   "--langs", ",".join(item.get("languages") or []),
                   "--out", str(result_path), "--max-wait", str(args.boot_timeout)]
            if only_langs:
                cmd += ["--only-langs", only_langs]
            rc, out = run(cmd, args.boot_timeout + TRAINED_MAX + 120, Path(workroot) / "probe.log")
            if not result_path.exists():
                reason = (f"timed out booting after {args.boot_timeout + TRAINED_MAX + 120}s" if rc is None
                          else f"probe crashed (exit {rc})")
                return {"status": "fail", "reason": reason}, out
            return json.loads(result_path.read_text()), out

        probe, out = probe_once()
        booted = probe.get("languages_booted") or []
        if (item["kind"] == "skill" and probe.get("status") == "fail" and len(booted) > 1
                and "failed to initialise" in (probe.get("reason") or "")):
            # A skill that fails with ALL its languages configured may only
            # be broken in one of them (ovos-skill-spelling 0.2.6: a bad
            # ro-ro regex). A device only loads its own languages, so that
            # is a per-language defect, not "doesn't load". Retry with the
            # primary language alone; if that loads, try each other
            # language alone to name the broken ones.
            primary, primary_out = probe_once(booted[0])
            if primary.get("status") == "pass":
                failing, by_lang = [], dict(primary.get("intents_by_lang") or {})
                for lang in booted[1:]:
                    one, _ = probe_once(lang)
                    if one.get("status") == "pass":
                        by_lang.update(one.get("intents_by_lang") or {})
                    else:
                        failing.append(lang)
                if failing:
                    primary["languages_booted"] = booted
                    primary["intents_by_lang"] = dict(sorted(by_lang.items()))
                    primary["languages_missing"] = failing
                    primary["warnings"] = [
                        "fails to load when these languages are configured: " + ", ".join(failing)
                        + " (loads with the others; see log excerpt)"]
                    probe, out = primary, out  # keep the multi-language failure log
                else:
                    # Every language loads on its own: the failure only happens
                    # in combination, which a device with all of them would hit.
                    probe["reason"] += " (each language loads on its own; fails only in combination)"

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
            cfg = config_message(out, probe.get("plugin_ids"), probe.get("module_roots"))
            if cfg:
                rec.update(status="needs_config", stage="load",
                           reason=f"needs configuration before it can load: {cfg}",
                           log_excerpt=excerpt(out))
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
                      args.boot_timeout + TRAINED_MAX + 120, Path(workroot) / "canary.log")
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
