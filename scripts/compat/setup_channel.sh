#!/usr/bin/env bash
# Build the base venv for one release channel by running ovos-test-harness's
# own channel install, unchanged. Reused, not rebuilt: the harness owns the
# precedence rules (constraints win, git leftovers --no-deps, ovoscope floor)
# and we want exactly its stack.
#
# Usage: setup_channel.sh <channel> <harness-checkout> <venv-dir> <work-dir>
# Leaves in <work-dir>: constraints-<channel>.txt, stack-freeze.txt,
# stack.json (key package versions).
set -euo pipefail
CHANNEL="${1:?channel}"
HARNESS="$(cd "${2:?harness checkout}" && pwd)"
VENV="${3:?venv dir}"
WORK="${4:?work dir}"
mkdir -p "$WORK"
WORK="$(cd "$WORK" && pwd)"

python3 -m venv "$VENV"
# A fresh venv gets the pip bundled with Python 3.11 (24.0), whose resolver
# gives up on the stable stack (ResolutionImpossible on ovos-plugin-manager)
# where a current pip resolves it. Pinned, not "latest", so a pip release
# cannot silently change results.
"$VENV/bin/python" -m pip install --disable-pip-version-check -q "pip==${COMPAT_PIP_VERSION:-26.2.1}"
# install_channel.sh calls `python3 -m pip`, so the venv must be first on PATH.
export PATH="$VENV/bin:$PATH"
export VIRTUAL_ENV="$VENV"

bash "$HARNESS/test/channel_compat/install_channel.sh" "$CHANNEL" "$WORK"

# Test driver. install_channel.sh keeps a channel's own ovoscope pin, and
# otherwise installs the harness's current ovoscope --no-deps. For the
# harness's conformance suite that is deliberate (its known-gaps baseline
# absorbs what breaks), but here it would make every boot fail the same way
# on an old channel: ovoscope >= 0.7 declares ovos-core >= 2 and calls APIs
# that stable's ovos-core 1.3 / ovos-bus-client 1.3 do not have. So when the
# installed ovoscope's own declared requirements are not met, it is replaced
# by the newest ovoscope pip can resolve under the channel's constraints:
# the driver that says it supports this stack. The stack itself is untouched.
if python3 -m pip check --disable-pip-version-check 2>/dev/null | grep -qi '^ovoscope '; then
  echo "==> ovoscope $(python3 -c 'from importlib.metadata import version; print(version("ovoscope"))') does not support this channel's stack; resolving one that does"
  python3 -m pip uninstall -q -y ovoscope
  python3 -m pip install --disable-pip-version-check --pre -c "$WORK/constraints-$CHANNEL.txt" ovoscope
fi

python3 -m pip freeze --disable-pip-version-check > "$WORK/stack-freeze.txt"
python3 - "$WORK/stack.json" <<'EOF'
import json, sys, platform
from importlib.metadata import version, PackageNotFoundError
out = {"python": platform.python_version(), "packages": {}}
for p in ("ovos-core", "ovos-workshop", "ovos-bus-client", "ovos-padatious",
          "ovos-adapt-parser", "ovos-plugin-manager", "ovos-config", "ovos-utils",
          "ovoscope"):
    try:
        out["packages"][p] = version(p)
    except PackageNotFoundError:
        out["packages"][p] = None
json.dump(out, open(sys.argv[1], "w"), indent=2)
EOF
cat "$WORK/stack.json"
