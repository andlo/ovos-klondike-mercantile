#!/usr/bin/env bash
# Local reproduction of one CI test shard, in a container close to the
# GitHub runner (Debian + Python 3.11). Usage: local_run.sh <channel> <items.json> <outdir>
set -euo pipefail
CHANNEL="$1"; ITEMS="$(realpath "$2")"; OUT="$(realpath -m "$3")"
REPO="$(cd "$(dirname "$0")/../.." && pwd)"
HARNESS="${HARNESS:-$HOME/ovos-test-harness}"
mkdir -p "$OUT"
podman run --rm --cgroup-manager=cgroupfs \
  -v "$REPO:/repo:ro,z" -v "$HARNESS:/harness:ro,z" -v "$ITEMS:/items.json:ro,z" -v "$OUT:/out:z" \
  docker.io/library/python:3.11-bookworm bash -c "
    set -euo pipefail
    apt-get update -qq && apt-get install -y -qq swig libfann-dev >/dev/null
    bash /repo/scripts/compat/setup_channel.sh $CHANNEL /harness /opt/base /out/stack > /out/setup.log 2>&1
    python3 /repo/scripts/compat/run_shard.py --channel $CHANNEL \
      --constraints /out/stack/constraints-$CHANNEL.txt --base-venv /opt/base \
      --items /items.json --out /out/results.json
  "
