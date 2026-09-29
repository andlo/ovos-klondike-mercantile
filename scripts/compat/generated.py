"""Thin adapter over `ovoscope generate` (OpenVoiceOS/ovoscope#224).

Generated utterances are drafted from a skill's own .intent/.entity files,
so a skill without hand-written golden files can still be routed at level 3.
The generator is under review upstream, so this adapter depends on as
little of it as possible:

  * it only calls the CLI (`ovoscope generate ...`), never imports it;
  * of the rows it only reads the `source` field, and keeps a row only when
    `source == "generated"`; everything else in a row is passed on unread,
    as the golden-row format `ovoscope golden` already runs;
  * an ovoscope without the `generate` subcommand makes the result
    "unavailable" (not a failure), so Klondike keeps working whether #224
    lands, changes or is replaced by a standalone package.

The generator runs from its own venv (GENERATOR_SPEC in the workflow), not
from the channel stack: generating is a static read of the checkout and
must not change what the channel is tested against.

Exit codes of `ovoscope generate` used here: 0 rows written, 2 no rows
(no .intent templates, or every template skipped). Anything else is an
"error" for this skill.
"""
import json
import subprocess
from pathlib import Path

GENERATE_TIMEOUT = 300
MAX_PER_INTENT = 10


def available(ovoscope_bin):
    """True when this ovoscope has the `generate` subcommand."""
    if not ovoscope_bin or not Path(ovoscope_bin).exists():
        return False
    try:
        proc = subprocess.run([str(ovoscope_bin), "generate", "--help"],
                              capture_output=True, timeout=60)
    except (OSError, subprocess.TimeoutExpired):
        return False
    return proc.returncode == 0


def generate(ovoscope_bin, skill_id, checkout, langs, out_path, report_path=None):
    """Run the generator for one skill checkout.

    Returns {"status": "ok"|"none"|"unavailable"|"error", "rows": n, "reason": ...}
    and, for "ok", writes only the generated rows to out_path.
    """
    if not available(ovoscope_bin):
        return {"status": "unavailable",
                "reason": "the installed ovoscope has no `generate` subcommand"}
    raw = Path(out_path).with_suffix(".raw.jsonl")
    cmd = [str(ovoscope_bin), "generate", "--skill", skill_id, "--checkout", str(checkout),
           "--out", str(raw), "--max-per-intent", str(MAX_PER_INTENT), "--force"]
    for lang in langs or []:
        cmd += ["--lang", lang]
    if report_path:
        cmd += ["--report", str(report_path)]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=GENERATE_TIMEOUT)
    except subprocess.TimeoutExpired:
        return {"status": "error", "reason": f"ovoscope generate timed out after {GENERATE_TIMEOUT}s"}
    if proc.returncode == 2:
        return {"status": "none", "rows": 0,
                "reason": "no rows: no .intent templates, or every template was skipped"}
    if proc.returncode != 0 or not raw.exists():
        tail = (proc.stderr or proc.stdout or "").strip().splitlines()[-3:]
        return {"status": "error", "reason": f"ovoscope generate exit {proc.returncode}: "
                                             + " | ".join(tail)[:300]}
    kept = []
    for line in raw.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            source = json.loads(line).get("source")
        except (ValueError, AttributeError):
            continue
        if source == "generated":
            kept.append(line)
    raw.unlink()
    if not kept:
        return {"status": "none", "rows": 0, "reason": "no rows marked source=generated"}
    Path(out_path).write_text("\n".join(kept) + "\n", encoding="utf-8")
    return {"status": "ok", "rows": len(kept)}
