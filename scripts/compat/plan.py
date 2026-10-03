#!/usr/bin/env python3
"""Decide what the compat run tests, and split it into shards.

Tested: Looks Complete (tier 1) Skills and Pipeline Plugins that are not
archived, plus everything the OVOS installer installs on the channel,
whatever its store status (issue #54, compat/installer.py): an archived
skill or a "Memory Plugin" the installer still uses reaches users all the
same. Other plugin types (TTS, STT, wake word ...) need hardware or models
and are not meaningful in MiniCroft.

Version tested per channel: the newest release on PyPI that the channel's
constraints allow. For a package the channel does not pin that is simply the
latest release; for one it pins (41 skills on stable) it is what a device on
that channel actually runs. PyPI is asked directly rather than trusting the
feed's pypi_version, because the crawler only refreshes an entry when its
rotation slot comes up (~18h), and a new release should be tested the same
night.

Incremental: a (package, channel) is re-tested only when its key changes:
package, resolved version, channel, the channel's effective stack, languages
booted, the pinned ovos-test-harness SHA and RUNNER_VERSION. Results with
status "error" (infra trouble) are always retried.

The effective stack (issue #39) is what the channel installs today of the
packages that decide whether a skill loads and where an utterance goes
(STACK_PACKAGES), resolved against PyPI like the skills themselves. It
replaced a hash of the whole constraints file, which re-tested everything
when any unrelated line moved (ovos-releases changes the alpha file several
times a day) and nothing when alpha's floors stayed put while a new
ovos-core pre-release came out. If PyPI can't be reached for the core
packages, the key falls back to the file hash for that run.

Level 3 has two baselines, each with its own key on top of `key`: the
installer's defaults (route_key, in every shard) and the Klondike profile
(issue #13). The Klondike part is one job per channel: the profile is
booted once, with every skill that passed level 2 there (as of the last
run) loaded next to it. It runs when the profile, the channel or any of
those skills changed.
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
ROUTE_VERSION = "5"  # 3: the stop check (#16); 4: OCP picks count as taken; 5: ovos-routing-judge (#48)
# The routing judge's pin (compat/routing-judge.txt) is part of the level 3
# keys too: a new judge release re-tests level 3 by itself.
ROUTING_JUDGE = next((l.strip() for l in (Path(__file__).resolve().parents[2] / "compat" / "routing-judge.txt")
                      .read_text().splitlines() if l.strip() and not l.lstrip().startswith("#")), "")
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


# What decides whether a skill loads and where an utterance goes. The exact
# version counts for core and the intent engines; for the rest, a new patch
# release doesn't re-test the store (major.minor).
STACK_EXACT = ("ovos-core", "ovos-workshop", "ovos-bus-client", "ovos-plugin-manager",
               "ovos-padatious", "padacioso", "ovos-adapt-parser")
STACK_MINOR = ("ovos-config", "ovos-utils", "ovos-m2v-pipeline", "ovos-common-query-pipeline-plugin",
               "ovos-ocp-pipeline-plugin", "ovos-persona", "ovos-fallback-pipeline-plugin",
               "ovos-stop-pipeline-plugin", "ovos-converse-pipeline-plugin")
STACK_PACKAGES = STACK_EXACT + STACK_MINOR
# Without these the stack says nothing; then the file hash is used instead.
STACK_REQUIRED = ("ovos-core", "ovos-workshop")


def resolve_channel_version(releases, spec, channel):
    """The version a device on `channel` installs: alpha installs pre-releases
    (the installer allows them), so its newest release that meets the floor;
    the other channels as resolve_version()."""
    if channel != "alpha" or not releases:
        return resolve_version(releases, spec)
    allowed = list(SpecifierSet(spec or "", prereleases=True).filter(releases, prereleases=True))
    return str(allowed[-1]) if allowed else None


def stack_level(package, version):
    """What of a version counts for the key (see STACK_EXACT)."""
    if version is None or package in STACK_EXACT:
        return version
    try:
        v = Version(version)
    except InvalidVersion:
        return version
    return f"{v.major}.{v.minor}"


def effective_stack(pins, channel, stack_releases):
    """{package: version} a device on this channel installs today."""
    out = {}
    for pkg in STACK_PACKAGES:
        version = resolve_channel_version(stack_releases.get(pkg), pins.get(normalize(pkg), ""), channel)
        if version:
            out[pkg] = version
    return out


def stack_signature(stack, csha):
    """The constraints part of the key: the effective stack, or the file hash
    when the stack couldn't be resolved (no PyPI)."""
    if all(stack.get(p) for p in STACK_REQUIRED):
        return {"stack": sorted((p, stack_level(p, v)) for p, v in stack.items())}
    return {"constraints_sha256": csha}


def stack_moves(old, new):
    """['ovos-core 3.7.1a3 -> 3.7.2a1', ...] between two effective stacks."""
    old, new = old or {}, new or {}
    return [f"{p} {old.get(p) or '-'} -> {new.get(p) or '-'}"
            for p in STACK_PACKAGES if old.get(p) != new.get(p) and (old or new)]


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
    prev_doc = json.loads(results_path.read_text()) if results_path.exists() else {}
    previous = prev_doc.get("results", {})
    prev_klondike = prev_doc.get("klondike") or {}
    profile_def = load_profile_def(baseline, Path(__file__).resolve().parents[2])
    feed_by_id = {e["id"]: e for e in feed}
    only = {s.strip() for s in args.only.split(",") if s.strip()}

    candidates = [e for e in feed if is_candidate(e) and (not only or e["id"] in only)]
    # What the installer installs, per channel (#54): read before the PyPI
    # lookups so its entries get a resolved version too.
    extra_reqs = (profile_def or {}).get("extra_requirements") or []
    stack_releases = {}
    with ThreadPoolExecutor(max_workers=8) as pool:
        for pkg, rel in zip(STACK_PACKAGES, pool.map(pypi_releases, STACK_PACKAGES)):
            stack_releases[pkg] = rel
    channels = [c.strip() for c in args.channels.split(",") if c.strip()]
    installer = {}
    if baseline:
        from compat.installer import core_requires, entries as installer_entries
        for channel in channels:
            pins = parse_constraints(fetch(CONSTRAINTS_URL.format(channel=channel)).decode())
            core = effective_stack(pins, channel, stack_releases).get("ovos-core")
            requires = core_requires(core) if core else []
            if not requires:
                print(f"warning: {channel}: ovos-core {core} requirements unknown, "
                      f"installer entries follow the store rule", file=sys.stderr)
            installer[channel] = installer_entries(feed, requires, baseline["requirements"], extra_reqs,
                                                   baseline["pipeline"], previous)
    extra_ids = {sid for m in installer.values() for sid in m
                 if sid in feed_by_id and (not only or sid in only)}
    candidates += [feed_by_id[sid] for sid in sorted(extra_ids - {e["id"] for e in candidates})]
    # Curated profile entries need a resolved version too, also in an --only run.
    curated = [feed_by_id[c["id"]] for c in ((profile_def or {}).get("curated") or {}).get("skills", [])
               + ((profile_def or {}).get("curated") or {}).get("pipeline", []) if c["id"] in feed_by_id]
    lookup = {e["id"]: e for e in candidates + curated}
    releases = {}
    with ThreadPoolExecutor(max_workers=8) as pool:
        for e, rel in zip(lookup.values(), pool.map(lambda e: pypi_releases(package_of(e, installer)),
                                                   lookup.values())):
            releases[e["id"]] = rel

    cdir = Path(args.constraints_dir)
    cdir.mkdir(parents=True, exist_ok=True)
    matrix, summary, klondike = [], {}, {}
    for channel in channels:
        raw = fetch(CONSTRAINTS_URL.format(channel=channel))
        (cdir / f"constraints-{channel}.txt").write_bytes(raw)
        csha = hashlib.sha256(raw).hexdigest()
        pins = parse_constraints(raw.decode())
        stack = effective_stack(pins, channel, stack_releases)
        ssig = stack_signature(stack, csha)
        if "constraints_sha256" in ssig:
            print(f"warning: {channel}: core packages not resolved on PyPI, keying on the constraints file",
                  file=sys.stderr)
        prev_stack = ((prev_doc.get("channels") or {}).get(channel) or {}).get("resolved_stack")
        moved = stack_moves(prev_stack, stack) if prev_stack else []
        kprof = channel_profile(profile_def, baseline, channel, feed_by_id, previous, pins, releases) \
            if profile_def else None
        todo, skipped, unresolved = [], 0, []
        inst = installer.get(channel) or {}
        for e in candidates:
            if not is_candidate(e) and e["id"] not in inst:
                continue  # installed by the installer on another channel only
            package = package_of(e, installer)
            pkg = normalize(package)
            pinned = pkg in pins
            version = resolve_version(releases.get(e["id"]), pins.get(pkg, ""))
            if version is None:
                unresolved.append(e["id"])
                continue
            langs = sorted(set(e.get("languages") or []))
            kind = (inst.get(e["id"]) or {}).get("kind") or TESTED_TYPES[e["component_type"]]
            key = key_for([package, version, channel, ssig, langs,
                           args.harness_sha, RUNNER_VERSION])
            route_key = key_for([key, baseline["sha256"], args.generator_spec, ROUTE_VERSION, ROUTING_JUDGE]) \
                if baseline and kind == "skill" else None
            prev = previous.get(e["id"], {}).get(channel)
            if (prev and prev.get("key") == key and prev.get("status") in FINAL_STATUSES
                    and route_current(prev, route_key)
                    and not (args.force or args.full)):
                skipped += 1
                continue
            todo.append({"id": e["id"], "package": package, "version": version,
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
        if kprof:
            kitems = klondike_items(feed, previous, channel, pins, inst)
            kprof["self_key"] = key_for([ssig, kprof["sha256"], args.harness_sha, RUNNER_VERSION,
                                         args.generator_spec, ROUTE_VERSION, ROUTING_JUDGE,
                                         sorted((i["id"], i["version"]) for i in kitems)])
            kprof["tested"] = len(kitems)
            prev_self = prev_klondike.get(channel) or {}
            if prev_self.get("key") != kprof["self_key"] or args.force or args.full:
                matrix.append({"channel": channel, "shard": "klondike", "items": [],
                               "klondike": json.dumps({"requirements": kprof["requirements"],
                                                       "pipeline": kprof["pipeline"],
                                                       "exclude_ids": device_bound(previous, channel),
                                                       "feed_map": feed_map(feed, inst), "items": kitems})})
        summary[channel] = {"constraints_sha256": csha, "resolved_stack": stack,
                            "keyed_on": "stack" if "stack" in ssig else "constraints file",
                            "stack_moved": moved, "to_test": len(todo),
                            "unchanged": skipped, "no_installable_release": unresolved,
                            "installer": inst}
        if kprof:
            klondike[channel] = kprof
        print(f"{channel}: {len(todo)} to test, {skipped} unchanged, "
              f"{len(unresolved)} without an installable release", file=sys.stderr)
        for line in moved:
            print(f"  {channel} moved: {line}", file=sys.stderr)

    Path(args.out).write_text(json.dumps({"include": matrix, "summary": summary,
                                          "harness_sha": args.harness_sha,
                                          "runner_version": RUNNER_VERSION,
                                          "route_version": ROUTE_VERSION,
                                          "baseline": baseline,
                                          "klondike": klondike,
                                          "klondike_profile": profile_def,
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


def route_current(prev, route_key, key_field="route_key", field="routing"):
    """Level 3 against one baseline is up to date for this result, or does
    not apply to it."""
    if route_key is None or prev.get("status") != "pass":
        return True
    return prev.get(key_field) == route_key and not (prev.get(field) or {}).get("error")


def load_profile_def(baseline, repo_root):
    """Installer extra skills + the curated TOML, or None (no level 3 at all,
    or the profile cannot be read: then only the Klondike part is skipped)."""
    if not baseline:
        return None
    from compat.baseline import load_extra_requirements, read_profile
    try:
        curated = read_profile(repo_root)
        extra = load_extra_requirements()
    except Exception as e:  # noqa: BLE001
        print(f"warning: Klondike profile unavailable, its routing is skipped: {e}", file=sys.stderr)
        return None
    return {"curated": curated, "extra_requirements": extra}


def channel_profile(profile_def, baseline, channel, feed_by_id, previous, pins, releases):
    """What the Klondike profile is on one channel: requirements to install,
    the pipeline, and which curated entries are in or out (and why). A
    curated entry is in when its own level 2 result on this channel passed."""
    from compat.baseline import insert_stages
    members, left_out, reqs = [], {}, []
    entries = profile_def["curated"]["skills"] + profile_def["curated"]["pipeline"]
    entries = list({c["id"]: c for c in reversed(entries)}.values())[::-1]  # a plugin with several stages: once
    for c in entries:
        e = feed_by_id.get(c["id"])
        rec = (previous.get(c["id"]) or {}).get(channel) or {}
        if e is None:
            left_out[c["id"]] = "not in the store"
            continue
        if rec.get("status") != "pass":
            left_out[c["id"]] = (f"level 2 on {channel}: {rec['status']}" if rec.get("status")
                                 else f"not tested on {channel} yet")
            continue
        pkg = normalize(e["package_name"])
        version = resolve_version(releases.get(c["id"]), pins.get(pkg, ""))
        if version is None:
            left_out[c["id"]] = "no release the channel allows"
            continue
        reqs.append(e["package_name"] if pkg in pins else f"{e['package_name']}=={version}")
        members.append(c["id"])
    plugins = [p for p in profile_def["curated"]["pipeline"] if p["id"] in members]
    pipeline, added, skipped = insert_stages(baseline["pipeline"], plugins)
    spec = {"requirements": list(baseline["requirements"]) + list(profile_def["extra_requirements"]) + reqs,
            "pipeline": pipeline, "added_stages": added, "stages_not_added": skipped,
            "curated_members": members, "left_out": left_out}
    # Versions are not in the sha on purpose: they come from the channel's
    # constraints (already in every key) or are the latest release, and a new
    # release of one profile skill should not re-run the whole store.
    installer = sorted(set(baseline["requirements"]) | set(profile_def["extra_requirements"]))
    spec["sha256"] = hashlib.sha256(json.dumps([installer, members, pipeline],
                                               sort_keys=True).encode()).hexdigest()
    return spec


def package_of(entry, installer):
    """The pip name to test an entry by: the store's, else the one the
    installer installs it as (#54: repos whose package name the crawler
    could not read)."""
    if entry.get("package_name"):
        return entry["package_name"]
    for m in installer.values():
        if entry["id"] in m:
            return m[entry["id"]]["package"]
    return None


def klondike_items(feed, previous, channel, pins, inst=None):
    """The skills the channel's Klondike job routes against the profile:
    every store skill that passed level 2 on the channel in the last run,
    at the version it was tested at. A skill tested for the first time in
    this run joins the next one."""
    out = []
    for e in feed:
        mine = (inst or {}).get(e["id"])
        if mine:
            if mine["kind"] != "skill":
                continue
        elif not is_candidate(e) or TESTED_TYPES.get(e["component_type"]) != "skill":
            continue
        rec = (previous.get(e["id"]) or {}).get(channel) or {}
        if rec.get("status") != "pass" or not rec.get("plugin_ids") or not rec.get("version_tested"):
            continue
        package = e.get("package_name") or mine["package"]
        out.append({"id": e["id"], "package": package, "version": rec["version_tested"],
                    "channel_pinned": normalize(package) in pins, "kind": "skill",
                    "repo": repo_url(e), "plugin_ids": list(rec["plugin_ids"])})
    return out


def feed_map(feed, inst=None):
    """{normalized package: {id, repo}} of every skill in the store, so the
    profile job can tell which installed skills are store entries (and fetch
    their golden files) without knowing what ovos-core[...] expands to."""
    out = {}
    for e in feed:
        if e.get("component_type") == "Skill" and e.get("package_name") and not e.get("archived"):
            out.setdefault(normalize(e["package_name"]), {"id": e["id"], "repo": repo_url(e)})
    # What the installer installs counts as a store skill too, archived or
    # not (#54), so the Klondike job fetches its golden files.
    by_id = {e["id"]: e for e in feed}
    for sid, m in (inst or {}).items():
        if m["kind"] == "skill" and sid in by_id:
            out.setdefault(normalize(m["package"]), {"id": sid, "repo": repo_url(by_id[sid])})
    return out


def repo_url(entry):
    src = entry.get("source") or ""
    return src if src.startswith("https://github.com/") else None


if __name__ == "__main__":
    sys.exit(main())
