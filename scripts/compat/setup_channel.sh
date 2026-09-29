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
# `pip check` exits non-zero whenever anything is unmet, and its output is
# captured before grepping: piping it straight into `grep -q` under
# `set -o pipefail` let grep close the pipe early, pip died of SIGPIPE, and
# the whole condition read as false on the runner (it passed locally only
# because pip happened to finish writing first).
driver_unmet() {
  local checks
  checks="$(python3 -m pip check --disable-pip-version-check 2>/dev/null || true)"
  grep -qi '^ovoscope ' <<<"$checks"
}
if driver_unmet; then
  echo "==> ovoscope $(python3 -c 'from importlib.metadata import version; print(version("ovoscope"))') does not support this channel's stack; resolving one that does"
  python3 -m pip uninstall -q -y ovoscope
  python3 -m pip install --disable-pip-version-check --pre -c "$WORK/constraints-$CHANNEL.txt" ovoscope
  if driver_unmet; then
    echo "::error::no ovoscope release supports the $CHANNEL stack" >&2
    exit 1
  fi
fi

# Default runtime plugins. A device's mycroft.conf names a translation and a
# language-detection module (ovos-translate-plugin-server and
# ovos-lang-detector-plugin-server, both from ovos-translate-server-plugin),
# and the installer puts them on every device. The harness stack leaves them
# out on stable, so any skill that creates self.translator in __init__
# (wikipedia, wolfie ...) would fail here and nowhere else. Installed under
# the channel's constraints, so the channel still decides the version.
python3 -m pip install --disable-pip-version-check -q -c "$WORK/constraints-$CHANNEL.txt" ovos-translate-server-plugin
python3 - <<'EOF'
from ovos_config import Configuration
from ovos_plugin_manager.language import find_tx_plugins, find_lang_detect_plugins
lang = Configuration().get("language", {})
missing = [m for m, found in ((lang.get("translation_module"), find_tx_plugins()),
                              (lang.get("detection_module"), find_lang_detect_plugins()))
           if m and m not in found]
if missing:
    raise SystemExit(f"default language plugins not loadable: {missing}")
print("==> default language plugins present:", lang.get("translation_module"), lang.get("detection_module"))
EOF

python3 -m pip freeze --disable-pip-version-check > "$WORK/stack-freeze.txt"
python3 - "$WORK/stack.json" <<'EOF'
import json, sys, platform
from importlib.metadata import version, PackageNotFoundError
out = {"python": platform.python_version(), "packages": {}}
for p in ("ovos-core", "ovos-workshop", "ovos-bus-client", "ovos-padatious",
          "ovos-adapt-parser", "ovos-plugin-manager", "ovos-config", "ovos-utils",
          "ovoscope", "ovos-translate-server-plugin"):
    try:
        out["packages"][p] = version(p)
    except PackageNotFoundError:
        out["packages"][p] = None
json.dump(out, open(sys.argv[1], "w"), indent=2)
EOF
cat "$WORK/stack.json"
