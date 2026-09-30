#!/usr/bin/env bash
# Local reproduction of one CI test shard, in a container close to the
# GitHub runner (Debian + Python 3.11). Usage: local_run.sh <channel> <items.json> <outdir>
#
# Level 3 runs when BASELINE is set (the JSON plan.py puts on each shard:
# python3 -c 'import json,sys; sys.path.insert(0,"scripts"); from compat.baseline import load; b=load(); print(json.dumps({"requirements": b["requirements"], "pipeline": b["pipeline"]}))').
# KLONDIKE is the "klondike" JSON plan.py puts on a shard (the profile; with
# "self": true the shard routes the profile against itself, items may be []).
# GENERATOR_SPEC is the pip spec of the ovoscope used for `generate`
# (default: none, i.e. generated runs report "unavailable").
set -euo pipefail
CHANNEL="$1"; ITEMS="$(realpath "$2")"; OUT="$(realpath -m "$3")"
REPO="$(cd "$(dirname "$0")/../.." && pwd)"
HARNESS="${HARNESS:-$HOME/ovos-test-harness}"
mkdir -p "$OUT"
printf '%s' "${BASELINE:-}" > "$OUT/baseline.json"
printf '%s' "${KLONDIKE:-}" > "$OUT/klondike-arg.json"
podman run --rm --cgroup-manager=cgroupfs \
  -e GENERATOR_SPEC="${GENERATOR_SPEC:-}" -e COMPAT_ROUTE_MAX_LANGS="${COMPAT_ROUTE_MAX_LANGS:-4}" \
  -e COMPAT_ROUTE_BUDGET_MIN="${COMPAT_ROUTE_BUDGET_MIN:-30}" \
  -e CHANNEL_CONSTRAINTS_BASE_URL="${CHANNEL_CONSTRAINTS_BASE_URL:-https://raw.githubusercontent.com/OpenVoiceOS/ovos-releases/main}" \
  -v "$REPO:/repo:ro,z" -v "$HARNESS:/harness:ro,z" -v "$ITEMS:/items.json:ro,z" -v "$OUT:/out:z" \
  docker.io/library/python:3.11-bookworm bash -c "
    set -euo pipefail
    apt-get update -qq && apt-get install -y -qq swig libfann-dev >/dev/null
    bash /repo/scripts/compat/setup_channel.sh $CHANNEL /harness /opt/base /out/stack > /out/setup.log 2>&1
    if [ -n \"\$GENERATOR_SPEC\" ]; then
      python3 -m venv /opt/gen && /opt/gen/bin/python -m pip install -q --disable-pip-version-check \"\$GENERATOR_SPEC\" > /out/generator.log 2>&1 || echo 'generator install failed (generated: unavailable)'
    fi
    python3 /repo/scripts/compat/run_shard.py --channel $CHANNEL \
      --constraints /out/stack/constraints-$CHANNEL.txt --base-venv /opt/base \
      --items /items.json --out /out/results.json \
      --baseline \"\$(cat /out/baseline.json)\" --klondike \"\$(cat /out/klondike-arg.json)\" \
      --generator /opt/gen/bin/ovoscope
  "
