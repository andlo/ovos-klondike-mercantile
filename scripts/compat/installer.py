"""What the OVOS installer puts on a device, as store entries (issue #54).

The store tests Looks Complete skills and pipeline plugins (feed.is_candidate).
Some of what the installer installs falls outside that rule: archived repos
still pulled in by ovos-core[skills-media], ovos-persona (a "Memory Plugin"
whose pipeline stages the installer uses), ... A user gets them all the same,
so they are always tested.

Read live, per channel:
  * skills: the installer's skills template (default profile) and its
    extra-skills template, with every ovos-core[extra] expanded through the
    requires_dist of the ovos-core version the channel installs (PyPI), so
    an extra that gains or loses a skill is followed without a code change;
  * pipeline plugins: the packages of ovos-core[plugins] (what the
    installer's core template installs) that provide a stage of the
    installer's pipeline, plus any store entry whose plugin ids from an
    earlier run name one of those stages (ovos-core itself: stop, converse,
    fallback).

Used by plan.py (stdlib + packaging only).
"""
import json
import re
import urllib.request

from packaging.markers import InvalidMarker
from packaging.requirements import InvalidRequirement, Requirement

# The interpreter the test runner uses (setup_python 3.11 in skill-compat.yml),
# for markers such as python_version >= "3.10".
PYTHON = "3.11"
# What the installer's core template installs of ovos-core (the pipeline
# plugins); "lgpl" too on ovos-core 1.x, where padatious lived there.
CORE_EXTRAS = ("plugins", "lgpl")
STAGE_SUFFIX = re.compile(r"-(high|medium|low)$")


def normalize(name):
    return re.sub(r"[-_.]+", "-", name or "").lower()


def stage_plugin(stage):
    """ovos-padatious-pipeline-plugin-high -> ovos-padatious-pipeline-plugin."""
    return STAGE_SUFFIX.sub("", stage)


def core_requires(version, fetch=None):
    """requires_dist of one ovos-core release, or [] when PyPI can't say."""
    url = f"https://pypi.org/pypi/ovos-core/{version}/json"
    try:
        if fetch:
            raw = fetch(url)
        else:
            req = urllib.request.Request(url, headers={"User-Agent": "ovos-klondike-mercantile compat"})
            with urllib.request.urlopen(req, timeout=30) as r:
                raw = r.read()
        return (json.loads(raw).get("info") or {}).get("requires_dist") or []
    except Exception:  # noqa: BLE001 - no PyPI: the run falls back to the store rule
        return []


def expand(lines, requires, extras_only=None):
    """Package names a list of requirement lines installs, with each
    ovos-core[extra,...] replaced by what that extra pulls in. Plain lines
    (ovos-skill-icanhazdadjokes) are kept; git+ URLs are skipped (no package
    to test by name). extras_only, when given, overrides the extras named on
    the lines (used for CORE_EXTRAS)."""
    out = []
    for line in lines:
        if line.startswith(("git+", "http", "-")):
            continue
        try:
            req = Requirement(line)
        except InvalidRequirement:
            continue
        if normalize(req.name) != "ovos-core":
            out.append(normalize(req.name))
            continue
        wanted = set(extras_only or req.extras)
        for dep in requires:
            try:
                d = Requirement(dep)
            except InvalidRequirement:
                continue
            if not d.marker:
                continue
            try:
                if any(d.marker.evaluate({"extra": x, "python_version": PYTHON, "python_full_version": PYTHON + ".0"})
                       for x in wanted):
                    out.append(normalize(d.name))
            except InvalidMarker:
                continue
    return list(dict.fromkeys(out))


def _repo_name(entry):
    src = entry.get("source") or ""
    return normalize(src.rstrip("/").rsplit("/", 1)[-1]) if src.startswith("https://github.com/") else ""


def store_lookup(feed):
    """normalized package -> feed entry: by package_name, else by the
    repo's name (entries the crawler could not read a package name from)."""
    by_pkg, by_repo = {}, {}
    for e in feed:
        if e.get("package_name"):
            by_pkg.setdefault(normalize(e["package_name"]), e)
        if _repo_name(e):
            by_repo.setdefault(_repo_name(e), e)
    return lambda pkg: by_pkg.get(pkg) or by_repo.get(pkg)


def entries(feed, requires, baseline_reqs, extra_reqs, pipeline, previous=None):
    """{store id: {"package", "kind", "profile"}} of what the installer
    installs on one channel. profile is "default" or "extra"; kind is
    "skill" or "pipeline". `requires` is the requires_dist of the ovos-core
    version the channel installs; `pipeline` the installer's stage ids."""
    find = store_lookup(feed)
    out = {}

    def add(pkg, kind, profile):
        e = find(pkg)
        if e and e["id"] not in out:
            out[e["id"]] = {"package": e.get("package_name") or pkg, "kind": kind, "profile": profile}

    for pkg in expand(baseline_reqs, requires):
        add(pkg, "skill", "default")
    for pkg in expand(extra_reqs or [], requires):
        add(pkg, "skill", "extra")

    bases = {stage_plugin(s) for s in pipeline or []}
    for pkg in expand(["ovos-core"], requires, extras_only=CORE_EXTRAS):
        if any(b == pkg or b.startswith(pkg + "-") for b in bases):
            add(pkg, "pipeline", "default")
    for sid, per_channel in (previous or {}).items():
        if sid in out:
            continue
        for rec in per_channel.values():
            if rec.get("kind") == "pipeline" and bases & set(rec.get("plugin_ids") or []):
                e = next((x for x in feed if x["id"] == sid), None)
                if e and e.get("package_name"):
                    out[sid] = {"package": e["package_name"], "kind": "pipeline", "profile": "default"}
                break
    return out
