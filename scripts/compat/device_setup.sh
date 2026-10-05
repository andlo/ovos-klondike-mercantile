#!/usr/bin/env bash
# Bring an installed OVOS device's virtualenv onto a release channel the same
# way Klondike builds its channel stacks, so a device runs the real channel
# and not whatever an installer's separate install batches happened to leave.
#
# Usage: device_setup.sh <stable|testing|alpha> [venv-dir]
#
# Prefer ovos-tui-client's `ovos-tui --set-channel <channel>` (0.3.0a2+): the
# same rules, plus a dry run and the TUI's own palette command. This script is
# for a device without ovos-tui-client, and is where those rules were first
# tried on hardware.
#
# Run it after ovos-installer, on the device, as the user owning the venv.
# Everything is read live (constraints and the harness stack), never stored.
#
#   1. Channel stack: the packages ovos-test-harness's requirements name that
#      the channel's constraints also name are installed BY NAME under
#      -c constraints (--upgrade), so the channel decides their version.
#      This is the stack setup_channel.sh gets from install_channel.sh,
#      limited to what the device has or its intent pipeline names (a
#      headless box gets no ovos-gui; a pipeline stage with its plugin
#      missing, like padatious, gets it).
#      pip is used without --pre: a pre-release is only taken where the
#      constraint line itself names one, so third-party dev releases
#      (httpx 1.0.devN) stay out.
#   2. Stack lock: ovos-core, ovos-workshop, ovos-bus-client,
#      ovos-plugin-manager, ovos-config and ovos-utils are pinned to what
#      step 1 installed (run_shard.py's LOCKED_STACK).
#   3. Everything else on the device that the channel names is upgraded by
#      name under the constraints AND the lock. A package that would need an
#      older core fails and is reported; it never downgrades the stack.
#
#   4. Pre-releases the channel does not name, pulled in as dependencies
#      (an installer resolving with pre-releases allowed), are moved to the
#      newest final release unless a dependent asks for the pre-release.
#
# Other packages the constraints file does not name are left as they are.
set -euo pipefail

CHANNEL="${1:?usage: device_setup.sh <stable|testing|alpha> [venv-dir]}"
case "$CHANNEL" in stable|testing|alpha) ;; *) echo "unknown channel: $CHANNEL" >&2; exit 2 ;; esac
VENV="${2:-$HOME/.venvs/ovos}"
WORK="${WORK:-$HOME/.cache/klondike-device/$CHANNEL}"
CONSTRAINTS_BASE="${CHANNEL_CONSTRAINTS_BASE_URL:-https://raw.githubusercontent.com/OpenVoiceOS/OpenVoiceOS/main}"
HARNESS_REQS="${HARNESS_REQUIREMENTS_URL:-https://raw.githubusercontent.com/OpenVoiceOS/ovos-test-harness/dev/requirements.txt}"
PY="$VENV/bin/python"
PIP=("$PY" -m pip install --disable-pip-version-check --progress-bar off)

mkdir -p "$WORK"
cd "$WORK"
STAMP="$(date +%Y%m%d-%H%M%S)"
"$PY" -m pip freeze --disable-pip-version-check > "freeze-before-$STAMP.txt"

echo "==> fetching constraints-$CHANNEL.txt and the harness stack"
curl -fsSL --retry 5 --retry-all-errors --retry-delay 3 "$CONSTRAINTS_BASE/constraints-$CHANNEL.txt" -o constraints.txt
curl -fsSL --retry 5 --retry-all-errors --retry-delay 3 "$HARNESS_REQS" -o harness-requirements.txt
echo "    constraints sha256 $(sha256sum constraints.txt | cut -d' ' -f1)"

"$PY" - <<'EOF'
import re
from importlib.metadata import distributions

norm = lambda n: re.sub(r"[-_.]+", "-", n or "").lower()
NAME = re.compile(r"^\s*([A-Za-z0-9][A-Za-z0-9._-]*)")
# Repos whose distribution name is not the repo name (as in the harness's
# test/channel_compat/resolve.py).
DIST_NAME_OVERRIDES = {
    "ovos-adapt-pipeline-plugin": "ovos-adapt-parser",
    "ovos-padatious-pipeline-plugin": "ovos-padatious",
}

def names(path):
    out = []
    for line in open(path):
        line = line.strip()
        if line.startswith("git+"):
            # git+https://github.com/OpenVoiceOS/ovos-core@dev -> ovos-core
            repo = norm(line.split("#", 1)[0].rsplit("/", 1)[-1].split("@", 1)[0].removesuffix(".git"))
            out.append(DIST_NAME_OVERRIDES.get(repo, repo))
            continue
        line = line.split("#", 1)[0].strip()
        if not line:
            continue
        m = NAME.match(line)
        if m:
            out.append(norm(m.group(1)))
    return list(dict.fromkeys(out))

# The harness's own test tooling is not part of a device stack.
TEST_TOOLS = {"ovoscope", "pytest", "pytest-json-report", "pytest-timeout", "ovos-spec-tools"}

channel = set(names("constraints.txt"))
installed = {norm(d.metadata["Name"]) for d in distributions()}

# The device's own intent pipeline: a stage's plugin belongs on the device
# even when the installer left it out (ovos-padatious-pipeline-plugin-high
# in mycroft.conf with no padatious installed).
pipeline = set()
try:
    from ovos_config import Configuration
    for stage in (Configuration().get("intents") or {}).get("pipeline") or []:
        plugin = norm(re.sub(r"-(high|medium|low)$", "", stage))
        pipeline.add(DIST_NAME_OVERRIDES.get(plugin, plugin))
except Exception as e:  # noqa: BLE001 - no config: only what is installed
    print(f"    (could not read the intent pipeline: {e})")

# The harness stack, limited to what this device has or its pipeline asks
# for: a headless box gets no ovos-gui just because the harness tests it.
harness = [n for n in names("harness-requirements.txt") if n in channel and n not in TEST_TOOLS]
stack = [n for n in harness if n in installed or n in pipeline]
skipped = [n for n in harness if n not in stack]
rest = sorted(n for n in installed & channel if n not in harness and n not in TEST_TOOLS)
open("stack.txt", "w").write("\n".join(stack) + "\n")
open("rest.txt", "w").write("\n".join(rest) + "\n")
print(f"    channel names {len(channel)} packages; stack {len(stack)}, other installed {len(rest)}")
added = [n for n in stack if n not in installed]
if added:
    print(f"    added for the device's pipeline: {', '.join(added)}")
if skipped:
    print(f"    harness stack not on this device, left out: {', '.join(skipped)}")
EOF

echo "==> [1/4] channel stack"
xargs -a stack.txt "${PIP[@]}" --upgrade -c constraints.txt -- > step1.log 2>&1 || { tail -30 step1.log; exit 1; }

echo "==> [2/4] stack lock"
# LOCKED_STACK from run_shard.py (tests/test_device_setup.py keeps them equal).
"$PY" - > lock.txt <<'EOF'
from importlib.metadata import version, PackageNotFoundError
for p in ("ovos-core", "ovos-workshop", "ovos-bus-client", "ovos-plugin-manager", "ovos-config", "ovos-utils"):
    try:
        print(f"{p}=={version(p)}")
    except PackageNotFoundError:
        pass
EOF
sed 's/^/    /' lock.txt

echo "==> [3/4] everything else the channel names"
: > failed.txt
if ! xargs -a rest.txt "${PIP[@]}" --upgrade -c constraints.txt -c lock.txt -- > step3.log 2>&1; then
  echo "    batch did not resolve; installing one by one to find the blockers"
  while read -r p; do
    [ -n "$p" ] || continue
    if ! "${PIP[@]}" --upgrade -c constraints.txt -c lock.txt "$p" > "step3-$p.log" 2>&1; then
      reason="$(grep -A3 'The conflict is caused by' "step3-$p.log" | tail -n +2 | sed 's/^ *//' | awk 'NF && !seen[$0]++' | paste -sd';' | cut -c1-300 || true)"
      echo "$p: ${reason:-see step3-$p.log}" >> failed.txt
    fi
  done < rest.txt
fi

echo "==> [4/4] pre-releases nothing asks for"
# The channel only names OVOS packages. Klondike's pip (no --pre) takes a
# pre-release of anything else only when a requirement asks for one; an
# installer resolving with pre-releases allowed may have pulled in betas
# (pydantic, lxml, tornado ...). Each pre-release the constraints do not
# name, and that is a dependency of something else (not a tool installed on
# purpose, like ovos-tui-client), is moved to the newest stable release
# below it under the constraints and the lock. If something needs the
# pre-release, pip refuses and it stays.
"$PY" - > prereleases.txt <<'EOF'
import re
from importlib.metadata import distributions
from packaging.requirements import Requirement
from packaging.version import Version

norm = lambda n: re.sub(r"[-_.]+", "-", n or "").lower()
NAME = re.compile(r"^\s*([A-Za-z0-9][A-Za-z0-9._-]*)")
named = set()
for line in open("constraints.txt"):
    m = NAME.match(line.split("#", 1)[0])
    if m:
        named.add(norm(m.group(1)))
dists = list(distributions())
# What every installed package asks of each dependency. pip does not check
# installed dependents when told to install "x<v", so their specifiers go
# into the request: one that needs the pre-release makes it unsatisfiable.
asked = {}
for d in dists:
    for r in d.requires or []:
        try:
            req = Requirement(r)
        except Exception:
            continue
        if req.marker and "extra" in str(req.marker):
            continue
        asked.setdefault(norm(req.name), []).extend(str(s) for s in req.specifier)
for d in dists:
    n = norm(d.metadata["Name"])
    try:
        pre = Version(d.version).is_prerelease
    except Exception:
        continue
    if not pre or n in named or n not in asked:
        continue
    specs = sorted(set(asked[n]))
    def is_pre(s):
        try:
            return Version(re.sub(r"^[<>=!~]+", "", s).removesuffix(".*")).is_prerelease
        except Exception:
            return False
    if any(is_pre(s) for s in specs):
        print(n, d.version, "-")  # a dependent asks for a pre-release: keep it
        continue
    # "<base" without a pre-release in it, so pip stays on final releases.
    print(n, d.version, ",".join([f"<{Version(d.version).base_version}"] + specs))
EOF
: > prerelease-kept.txt
while read -r p v spec; do
  [ -n "$p" ] || continue
  if [ "$spec" = "-" ]; then
    echo "$p $v (a dependent asks for a pre-release)" >> prerelease-kept.txt
  elif ! "${PIP[@]}" -c constraints.txt -c lock.txt "$p$spec" > "step4-$p.log" 2>&1; then
    echo "$p $v (no final release fits; see step4-$p.log)" >> prerelease-kept.txt
  fi
done < prereleases.txt

"$PY" -m pip freeze --disable-pip-version-check > "freeze-after-$STAMP.txt"
echo
echo "==> changed"
changes="$(diff <(sort "freeze-before-$STAMP.txt") <(sort "freeze-after-$STAMP.txt") | grep -E '^[<>]' || true)"
if [ -n "$changes" ]; then sed 's/^/    /' <<<"$changes"; else echo "    nothing"; fi
echo
echo "==> cannot follow the channel (left as installed)"
if [ -s failed.txt ]; then sed 's/^/    /' failed.txt; else echo "    none"; fi
echo
echo "==> pre-releases kept (outside the channel)"
if [ -s prerelease-kept.txt ]; then sed 's/^/    /' prerelease-kept.txt; else echo "    none"; fi
echo
echo "==> pip check"
"$PY" -m pip check --disable-pip-version-check 2>&1 | sed 's/^/    /' || true
echo
echo "==> restart OVOS to load the new versions"
