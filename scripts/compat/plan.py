#!/usr/bin/env python3
"""Decide what the compat run tests, and split it into shards.

Tested: Looks Complete (tier 1) Skills and Pipeline Plugins that are not
archived. Other plugin types (TTS, STT, wake word ...) need hardware or
models and are not meaningful in MiniCroft.

Version tested per channel: the newest release on PyPI that the channel's
constraints allow. For a package the channel does not pin that is simply the
latest release; for one it pins (41 skills on stable) it is what a device on
that channel actually runs. PyPI is asked directly rather than trusting the
feed's pypi_version, because the crawler only refreshes an entry when its
rotation slot comes up (~18h), and a new release should be tested the same
night.

Incremental: a (package, channel) is re-tested only when its key changes:
package, resolved version, channel, constraints hash, languages booted,
the pinned ovos-test-harness SHA and RUNNER_VERSION. Results with status
"error" (infra trouble) are always retried.
"""
import argparse
import hashlib
import json
import re
import sys
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from packaging.specifiers import SpecifierSet
from packaging.version import InvalidVersion, Version

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from compat.feed import FINAL_STATUSES, TESTED_TYPES, is_candidate  # noqa: E402

# Bump when probe.py/run_shard.py change what a result means; every package
# is then re-tested once.
RUNNER_VERSION = "1"
# Level 3 has its own key (route_key) on top of `key`: the baseline
# (installer skills + pipeline), the generator and ROUTE_VERSION. A skill
# that loaded is re-tested when either key changes; one that did not load
# never reaches level 3, so only `key` matters for it. Bump when route.py
# or the level 3 parts of run_shard.py change what a result means.
ROUTE_VERSION = "1"
# The constraints the OVOS installer itself installs with
# (ovos-installer: ovos_virtualenv_constraints_url). OpenVoiceOS/OpenVoiceOS
# carries the same files today; the installer is the reference for "what a
# device on this channel runs".
CONSTRAINTS_BASE = "https://raw.githubusercontent.com/OpenVoiceOS/ovos-releases/main"
CONSTRAINTS_URL = CONSTRAINTS_BASE + "/constraints-{channel}.txt"
NAME_RE = re.compile(r"^\s*([A-Za-z0-9][A-Za-z0-9._-]*)\s*(\[[^\]]*\])?\s*([^;#]*)")


def normalize(name):
    return re.sub(r"[-_.]+", "-", name).lower()


def fetch(url, timeout=30):
    req = urllib.request.Request(url, headers={"User-Agent": "ovos-klondike-mercantile compat"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def parse_constraints(text):
    pins = {}
    for line in text.splitlines():
        line = line.split("#", 1)[0].strip()
        if not line or line.startswith("-"):
            continue
        m = NAME_RE.match(line)
        if m:
            pins[normalize(m.group(1))] = m.group(3).strip()
    return pins


def pypi_releases(package):
    try:
        data = json.loads(fetch(f"https://pypi.org/pypi/{package}/json"))
    except Exception:
        return None
    versions = []
    for v, files in (data.get("releases") or {}).items():
        if not files or all(f.get("yanked") for f in files):
            continue
        try:
            versions.append(Version(v))
        except InvalidVersion:
            continue
    return sorted(versions)


def resolve_version(releases, spec):
    """Newest release pip would pick under the channel constraint, or None."""
    if not releases:
        return None
    if not spec:
        stable = [v for v in releases if not v.is_prerelease]
        return str((stable or releases)[-1])
    allowed = list(SpecifierSet(spec).filter(releases))
    return str(allowed[-1]) if allowed else None


def key_for(parts):
    return hashlib.sha256(json.dumps(parts, sort_keys=True).encode()).hexdigest()[:16]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--feed", default="docs/skills.json")
    ap.add_argument("--results", default="docs/compat/results.json")
    ap.add_argument("--channels", default="stable,alpha")
    ap.add_argument("--harness-sha", required=True)
    ap.add_argument("--constraints-dir", required=True, help="where fetched constraints are written")
    ap.add_argument("--only", default="", help="comma-separated entry ids (test request)")
    ap.add_argument("--force", action="store_true", help="ignore existing keys")
    ap.add_argument("--full", action="store_true", help="re-test everything")
    ap.add_argument("--shard-size", type=int, default=8)
    ap.add_argument("--no-route", action="store_true", help="levels 1-2 only (no baseline fetch)")
    ap.add_argument("--generator-spec", default="", help="pip spec of the ovoscope used for `generate`")
    ap.add_argument("--out", required=True, help="matrix JSON")
    args = ap.parse_args()

    baseline = None
    if not args.no_route:
        from compat.baseline import load as load_baseline
        try:
            baseline = load_baseline()
            print(f"baseline: {baseline['requirements']} ({len(baseline['pipeline'])} pipeline stages)",
                  file=sys.stderr)
        except Exception as e:  # noqa: BLE001 - no baseline: this run stops at level 2
            print(f"warning: installer baseline unavailable, level 3 skipped: {e}", file=sys.stderr)

    feed = json.loads(Path(args.feed).read_text())
    results_path = Path(args.results)
    previous = json.loads(results_path.read_text()).get("results", {}) if results_path.exists() else {}
    only = {s.strip() for s in args.only.split(",") if s.strip()}

    candidates = [e for e in feed if is_candidate(e) and (not only or e["id"] in only)]
    releases = {}
    with ThreadPoolExecutor(max_workers=8) as pool:
        for e, rel in zip(candidates, pool.map(lambda e: pypi_releases(e["package_name"]), candidates)):
            releases[e["id"]] = rel

    cdir = Path(args.constraints_dir)
    cdir.mkdir(parents=True, exist_ok=True)
    channels = [c.strip() for c in args.channels.split(",") if c.strip()]
    matrix, summary = [], {}
    for channel in channels:
        raw = fetch(CONSTRAINTS_URL.format(channel=channel))
        (cdir / f"constraints-{channel}.txt").write_bytes(raw)
        csha = hashlib.sha256(raw).hexdigest()
        pins = parse_constraints(raw.decode())
        todo, skipped, unresolved = [], 0, []
        for e in candidates:
            pkg = normalize(e["package_name"])
            pinned = pkg in pins
            version = resolve_version(releases.get(e["id"]), pins.get(pkg, ""))
            if version is None:
                unresolved.append(e["id"])
                continue
            langs = sorted(set(e.get("languages") or []))
            kind = TESTED_TYPES[e["component_type"]]
            key = key_for([e["package_name"], version, channel, csha, langs,
                           args.harness_sha, RUNNER_VERSION])
            route_key = key_for([key, baseline["sha256"], args.generator_spec, ROUTE_VERSION]) \
                if baseline and kind == "skill" else None
            prev = previous.get(e["id"], {}).get(channel)
            if (prev and prev.get("key") == key and prev.get("status") in FINAL_STATUSES
                    and route_current(prev, route_key) and not (args.force or args.full)):
                skipped += 1
                continue
            todo.append({"id": e["id"], "package": e["package_name"], "version": version,
                         "channel_pinned": pinned, "kind": kind, "repo": repo_url(e),
                         "languages": langs if kind == "skill" else [], "key": key,
                         "route_key": route_key})
        for i in range(0, len(todo), args.shard_size):
            shard = {"channel": channel, "shard": i // args.shard_size + 1,
                     "items": todo[i:i + args.shard_size]}
            if baseline:
                shard["baseline"] = json.dumps({"requirements": baseline["requirements"],
                                                "pipeline": baseline["pipeline"],
                                                "exclude_ids": device_bound(previous, channel)})
            matrix.append(shard)
        summary[channel] = {"constraints_sha256": csha, "to_test": len(todo),
                            "unchanged": skipped, "no_installable_release": unresolved}
        print(f"{channel}: {len(todo)} to test, {skipped} unchanged, "
              f"{len(unresolved)} without an installable release", file=sys.stderr)

    Path(args.out).write_text(json.dumps({"include": matrix, "summary": summary,
                                          "harness_sha": args.harness_sha,
                                          "runner_version": RUNNER_VERSION,
                                          "route_version": ROUTE_VERSION,
                                          "baseline": baseline,
                                          "generator_spec": args.generator_spec}, indent=2))
    return 0


def device_bound(previous, channel):
    """Skill ids whose own level 2 result on this channel is needs_device:
    their load waits for device services (ovos-skill-boot-finished loops
    until network/GUI are ready) and would keep a routing boot from ever
    reaching READY. A default skill among them is left out of the baseline,
    and the detail page says so."""
    ids = set()
    for per in previous.values():
        # A skill not yet tested on this channel (a newly added channel, or
        # a new skill) is judged by its result on the other channels: one
        # device-bound default skill is enough to keep a routing boot from
        # ever reaching READY.
        recs = [per[channel]] if per.get(channel) else list(per.values())
        for rec in recs:
            if rec.get("status") == "needs_device":
                ids.update(rec.get("plugin_ids") or [])
    return sorted(ids)


def route_current(prev, route_key):
    """Level 3 is up to date for this result, or does not apply to it."""
    if route_key is None or prev.get("status") != "pass":
        return True
    return prev.get("route_key") == route_key and not (prev.get("routing") or {}).get("error")


def repo_url(entry):
    src = entry.get("source") or ""
    return src if src.startswith("https://github.com/") else None


if __name__ == "__main__":
    sys.exit(main())
