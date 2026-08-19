#!/usr/bin/env python3
"""
ovos-klondike-mercantile: a global, automatically-discovered directory
of OVOS skills across ALL of GitHub - not just one author's own work
(that's what ovos-skills-directory is for). Philosophy: cast a wide
net and include as much as possible, marking what's missing rather
than excluding anything that might genuinely be an OVOS skill.

Discovery combines two independent signals, unioned:
1. Code search for skill.json files containing "pip_spec" - found by
   testing several candidate search terms against real results;
   "skill_id" alone matched unrelated projects (an RPG skill-tree
   app, a notes repo) since that term isn't distinctive enough on
   its own, while "pip_spec" reliably matched only genuine OVOS
   skill.json files across several different authors/orgs.
2. Repos self-tagged with the "ovos" or "openvoiceos" GitHub topic -
   catches skills that exist but weren't found by signal 1 (skill.json
   missing, misplaced, or not yet written).

Every candidate gets one of three tiers, based on whether a formal
manifest was found for its actual type - not specifically a
skill.json, since most of what this store now covers isn't a skill:
- Tier 1 (Looks Complete): has a confirmed manifest for its type
  (skill.json for Skills, or a declared entry-points group for
  Plugins), published on PyPI, has a GitHub release.
- Tier 2 (Incomplete): has a confirmed manifest, but missing a PyPI
  release and/or a GitHub release - shown with an explicit "not on
  PyPI" / "no release" badge rather than excluded.
- Tier 3 (Inferred, Unconfirmed): NO formal manifest found at all.
  Falls through three last-resort signals, in order: skill-shaped
  __init__.py code (OVOSSkill/FallbackSkill/etc, guessed as "Skill"),
  then a real installable package with no skill/plugin-specific
  signal at all (guessed as "Tool" - catches CLI clients, helper
  libraries, and other genuinely OVOS-adjacent utilities that aren't
  skills or plugins). A topic-tagged repo matching none of these is
  excluded outright - the topic alone isn't proof of anything.
"""
import base64
import json
import re
import subprocess
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SKILLS_DIR = ROOT / "skills"
DOCS_DIR = ROOT / "docs"
FEED_PATH = DOCS_DIR / "skills.json"
META_PATH = DOCS_DIR / "meta.json"
OVOS_STORE_FEED_URL = "https://openvoiceos.github.io/OVOS-skills-store/skills.json"
IGNORE_LIST_PATH = ROOT / "ignore.txt"

PROVIDER_PATTERN = re.compile(r"provider for ([\w.-]+)", re.IGNORECASE)
ONLINE_LIBS = {"requests", "bs4", "beautifulsoup4", "feedparser", "aiohttp", "httpx"}

# Matches OVOS's own namespaced entry-point group names, e.g.
# "opm.ocp.extractor" or "ovos.plugin.pipeline" - these are the
# AUTHORITATIVE signal for what kind of component something is,
# since it's literally how ovos-plugin-manager discovers and
# categorizes plugins at runtime. Far more precise than guessing
# from class names in __init__.py. Works against both setup.py
# (dict-literal entry_points=) and pyproject.toml
# ([project.entry-points."..."]) - many newer OVOS repos have moved
# to pyproject.toml exclusively, found while investigating why OCP/
# pipeline/persona components were being skipped entirely.
ENTRY_POINT_GROUP_PATTERN = re.compile(r'"(ovos\.plugin\.[\w.]+|opm\.[\w.]+)"')

# Readable labels for known entry-point group suffixes (prefix
# "ovos.plugin."/"opm." stripped before matching). Checked as
# substrings, not exact matches, since real-world group names vary
# ("opm.ocp.extractor" vs "opm.ocp.extractor.config" should both
# read as the same component type). Anything not matched here still
# gets a readable fallback label instead of being dropped - see
# derive_component_type().
KNOWN_COMPONENT_TYPES = {
    "skill": "Skill",
    "ocp": "OCP Media Plugin",
    "pipeline": "Pipeline Plugin",
    "solver": "Solver Plugin",
    "persona": "Persona",
    "tts": "TTS Plugin",
    "stt": "STT Plugin",
    "wake_word": "Wake Word Plugin",
    "ww": "Wake Word Plugin",
    "phal": "PHAL Plugin",
    "g2p": "G2P Plugin",
    "vad": "VAD Plugin",
    "audio": "Audio Plugin",
    "transformer": "Transformer Plugin",
    "microphone": "Microphone Plugin",
}

# Signs of a real OVOS skill in __init__.py - used as a fallback only
# when no skill.json AND no entry-points group were found at all, to
# still catch skills missing formal packaging metadata.
SKILL_CODE_SIGNS = (
    "OVOSSkill", "FallbackSkill", "CommonQuerySkill",
    "ovos_workshop", "intent_handler", "create_skill",
)

CATEGORY_TAGS = {
    "education": "Education", "utility": "Utility", "entertainment": "Entertainment",
    "daily": "Daily", "music": "Music", "games": "Games", "productivity": "Productivity",
    "home": "Home", "information": "Information", "news": "News",
}

# Orgs/authors already confirmed (by hand, from real Klondike runs)
# to be genuine first-party parts of the OVOS ecosystem, not random
# personal accounts. Used ONLY to avoid excluding their forks - see
# the fork-check in main() for why "is a GitHub fork" alone isn't a
# reliable "skip this" signal: ovos-skill-alerts, ovos-skill-
# easter-eggs, ovos-skill-ip, and ovos-skill-date-time were ALL
# missing from the store entirely (not just badged oddly) because
# they're technically still registered as GitHub forks of their
# original Mycroft-AI predecessors, never detached - excluding them
# lost real, official, actively-maintained OpenVoiceOS skills, not
# noise.
TRUSTED_FORK_OWNERS = {
    "openvoiceos", "neongeckocom", "oscillatelabsllc",
    "tigregotico", "jarbashivemind", "smartgic",
}


def gh_json(*args, retries=4):
    """Runs `gh` and parses JSON output. Retries with exponential
    backoff specifically on GitHub's SECONDARY rate limit (abuse
    detection triggered by request bursts, distinct from the hourly
    primary limit) - caught the hard way in a real CI run: this
    script's per-candidate loop makes several sequential API calls
    with no pacing at all, and a fine-grained PAT hit secondary
    limits hard enough to silently fail ~40 consecutive calls
    (an entire org's worth of repos, all at the same millisecond
    timestamp - not a coincidence). Anything else still raises
    immediately - only rate-limit responses are worth retrying."""
    last_result = None
    for attempt in range(retries):
        result = subprocess.run(["gh", *args], capture_output=True, text=True)
        if result.returncode == 0:
            return json.loads(result.stdout)
        last_result = result
        if "rate limit" in result.stderr.lower() and attempt < retries - 1:
            wait = 2 ** (attempt + 2)  # 4s, 8s, 16s, 32s
            print(f"    (rate limited, waiting {wait}s before retry {attempt + 2}/{retries})")
            time.sleep(wait)
            continue
        break
    raise subprocess.CalledProcessError(
        last_result.returncode, last_result.args, last_result.stdout, last_result.stderr
    )


def gh_ok(*args):
    """Like gh_json, but returns None on any failure instead of
    raising - used for optional lookups (a repo without a
    settingsmeta.json, a missing file, etc.) where "not found" is a
    normal, expected outcome, not an error to propagate. Still
    benefits from gh_json's own rate-limit retry - only genuine
    "this doesn't exist" 404s end up silently returning None here."""
    try:
        return gh_json(*args)
    except subprocess.CalledProcessError:
        return None


def load_ignore_list():
    if not IGNORE_LIST_PATH.exists():
        return set()
    lines = IGNORE_LIST_PATH.read_text().splitlines()
    return {ln.strip() for ln in lines if ln.strip() and not ln.strip().startswith("#")}


def search_code_repos(query):
    names = set()
    page = 1
    while True:
        items = gh_json("api", f"search/code?q={query}&per_page=100&page={page}")["items"]
        if not items:
            break
        for item in items:
            names.add(item["repository"]["full_name"])
        if len(items) < 100:
            break
        page += 1
        if page > 10:  # hard safety cap against runaway pagination
            break
    return names


def search_topic_repos(topic):
    """GitHub's repository search EXCLUDES forks by default unless
    the query explicitly says fork:true - discovered the hard way:
    several real, actively-maintained official OpenVoiceOS skills
    (ovos-skill-alerts, ovos-skill-easter-eggs, ovos-skill-ip,
    ovos-skill-date-time) were missing from Klondike entirely, not
    just badged oddly, because they're technically still registered
    as GitHub forks of their original Mycroft-AI predecessors (never
    detached) - so they never even reached the fork-owner-allowlist
    check in main(), since this function never found them in the
    first place. fork:true here restores them to the candidate pool;
    main()'s TRUSTED_FORK_OWNERS check still decides which forks are
    actually kept."""
    names = set()
    page = 1
    while True:
        items = gh_json(
            "api", f"search/repositories?q=topic:{topic}+fork:true&per_page=100&page={page}"
        )["items"]
        if not items:
            break
        for item in items:
            names.add(item["full_name"])
        if len(items) < 100:
            break
        page += 1
        if page > 10:
            break
    return names


def repo_info(full_name):
    """Basic repo metadata - fork status, license, description,
    topics, last-push timestamp. Returns None if the repo is gone
    (deleted/renamed since discovery) - prints the REAL failure
    reason (not just "not accessible") since a prior version of this
    function swallowed the actual error and made a real bug (every
    OpenVoiceOS repo failing identically) look like generic
    inaccessibility instead of the specific cause it actually was."""
    try:
        return gh_json("api", f"repos/{full_name}")
    except subprocess.CalledProcessError as e:
        reason = (e.stderr or "").strip().splitlines()[0] if e.stderr else "(no stderr captured)"
        print(f"    DIAG repo_info({full_name}) failed: {reason}")
        return None


def fetch_file(full_name, path):
    content = gh_ok("api", f"repos/{full_name}/contents/{path}")
    if content is None or "content" not in content:
        return None
    try:
        return base64.b64decode(content["content"]).decode("utf-8", errors="ignore")
    except Exception:
        return None


def fetch_skill_json(full_name):
    for path in ("locale/en-us/skill.json", "locale/en-US/skill.json", "skill.json"):
        text = fetch_file(full_name, path)
        if text is None:
            continue
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            continue
    return None


def looks_like_skill_code(full_name):
    text = fetch_file(full_name, "__init__.py") or ""
    return any(sign in text for sign in SKILL_CODE_SIGNS)


def fetch_setup_and_pyproject(full_name):
    """Fetches setup.py and pyproject.toml ONCE per candidate and
    returns both texts (empty string if missing) for reuse by both
    entry-point-group detection and package-name guessing. Fixed
    after a real CI run burned through an entire hourly rate-limit
    budget partway through 300+ candidates: both files were
    previously being fetched TWICE per non-skill.json candidate (once
    in fetch_entry_point_groups, again in guess_package_name) -
    doubling API calls for no reason across roughly 270 topic-tagged
    candidates."""
    setup_text = fetch_file(full_name, "setup.py") or ""
    pyproject_text = fetch_file(full_name, "pyproject.toml") or ""
    return setup_text, pyproject_text


def derive_entry_point_groups(setup_text, pyproject_text):
    """Same signal as before (see ENTRY_POINT_GROUP_PATTERN) - now
    takes already-fetched text instead of fetching it itself."""
    groups = set()
    groups.update(ENTRY_POINT_GROUP_PATTERN.findall(setup_text))
    groups.update(ENTRY_POINT_GROUP_PATTERN.findall(pyproject_text))
    return groups


def derive_component_type(entry_point_groups):
    """Readable component type from a set of entry-point group
    names, or None if the set is empty. See KNOWN_COMPONENT_TYPES for
    the matched labels; anything else still gets a readable label
    derived from its own group name rather than being dropped -
    "opm.some_new_thing" becomes "Some New Thing Plugin"."""
    for group in entry_point_groups:
        suffix = group.replace("ovos.plugin.", "").replace("opm.", "")
        for key, label in KNOWN_COMPONENT_TYPES.items():
            if key in suffix:
                return label
        last_part = suffix.split(".")[-1].replace("_", " ")
        return f"{last_part.title()} Plugin"
    return None


def fetch_requires_api_key(full_name):
    text = fetch_file(full_name, "settingsmeta.json")
    if text is None:
        return False
    lowered = text.lower()
    return "api_key" in lowered or "api key" in lowered


MAX_SETUP_SECTION_LENGTH = 800

# Matches markdown headers whose text suggests installation/setup/
# configuration content - deliberately broad (install, setup,
# config, getting started) since repos phrase this differently, and
# a repo can have more than one matching section (e.g. separate
# "Installation" and "Configuration" headers).
SETUP_HEADING_PATTERN = re.compile(
    r"install|setup|config|getting started", re.IGNORECASE
)


def fetch_readme(full_name):
    """Fetches README.md (or common case-variant names), once, for
    reuse by both extract_readme_description() and
    extract_readme_setup_sections() - avoids fetching the same file
    twice for two different purposes."""
    for path in ("README.md", "readme.md", "Readme.md"):
        text = fetch_file(full_name, path)
        if text:
            return text
    return None


def extract_readme_description(readme_text):
    """Best-effort description from already-fetched README text,
    used ONLY as a last-resort fallback when neither skill.json nor
    GitHub's own repo "About" description field have anything -
    confirmed common specifically for PHAL plugins by inspection:
    ovos-PHAL-plugin-pulseaudio has a real, substantial README
    ("This is a PHAL plugin for OpenVoiceOS. It controls system
    volume through PulseAudio...") but an empty GitHub About field,
    leaving the card with no description text at all otherwise.
    Strips markdown headers, badge/image lines, and raw HTML lines,
    then takes the first line of real prose - deliberately simple
    (not a full markdown parser) since it only needs to find one
    readable sentence, not render the document."""
    if not readme_text:
        return ""
    for line in readme_text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("[!") or line.startswith("!["):
            continue
        if line.startswith("<"):
            continue
        line = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", line)
        if len(line) > 20:
            return line
    return ""


def extract_readme_setup_sections(readme_text):
    """Pulls out any README sections whose heading suggests
    installation/setup/configuration content - repo-specific steps
    beyond a plain `pip install X` (editing mycroft.conf, enabling a
    systemd service, setting an API key, etc) that a generic install
    command can't capture on its own. Returns a list of
    {heading, content} dicts, in document order - a repo can have
    more than one matching section. Content is capped at
    MAX_SETUP_SECTION_LENGTH so the feed doesn't balloon from a
    handful of repos with very long READMEs."""
    if not readme_text:
        return []
    lines = readme_text.splitlines()
    sections = []
    i = 0
    while i < len(lines):
        match = re.match(r"^(#{1,6})\s+(.*)$", lines[i])
        if match and SETUP_HEADING_PATTERN.search(match.group(2)):
            level = len(match.group(1))
            heading = match.group(2).strip()
            i += 1
            body_lines = []
            while i < len(lines):
                next_match = re.match(r"^(#{1,6})\s+", lines[i])
                if next_match and len(next_match.group(1)) <= level:
                    break
                body_lines.append(lines[i])
                i += 1
            body = "\n".join(body_lines).strip()
            if body:
                if len(body) > MAX_SETUP_SECTION_LENGTH:
                    body = body[:MAX_SETUP_SECTION_LENGTH].rstrip() + "…"
                sections.append({"heading": heading, "content": body})
            continue
        i += 1
    return sections


def derive_package_name(setup_text, pyproject_text):
    """Same signal as before (see guess_package_name's original
    docstring) - now takes already-fetched text instead of fetching
    it itself, see fetch_setup_and_pyproject()."""
    match = re.search(r"""name\s*=\s*["']([\w.-]+)["']""", setup_text)
    if match:
        return match.group(1)
    match = re.search(r"""^\s*name\s*=\s*["']([\w.-]+)["']""", pyproject_text, re.MULTILINE)
    return match.group(1) if match else None


def pypi_info(package_name):
    if not package_name:
        return None, [], None
    url = f"https://pypi.org/pypi/{package_name}/json"
    try:
        with urllib.request.urlopen(url, timeout=10) as resp:
            data = json.load(resp)
        info = data["info"]
        version = info["version"]
        release_files = data.get("releases", {}).get(version, [])
        release_date = release_files[0]["upload_time_iso_8601"] if release_files else None
        return version, (info.get("requires_dist") or []), release_date
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None, [], None
        raise
    except Exception:
        return None, [], None


def latest_github_release(full_name):
    data = gh_ok("api", f"repos/{full_name}/releases/latest")
    return data.get("tag_name") if data else None


def fetch_ovos_store_package_names():
    try:
        with urllib.request.urlopen(OVOS_STORE_FEED_URL, timeout=10) as resp:
            feed = json.load(resp)
        return {item.get("package_name") for item in feed.get("items", [])}
    except Exception:
        return set()


def extract_pipeline(description):
    if not description:
        return None
    match = PROVIDER_PATTERN.search(description)
    return match.group(1).rstrip(".") if match else None


def classify_connectivity(description, requires_dist):
    desc_lower = (description or "").lower()
    mentions_offline = bool(re.search(r"\boffline\b|\bno internet\b", desc_lower))
    mentions_online_fallback = bool(
        re.search(r"online fallback|optional.*online|fallback.*online", desc_lower)
    )
    if mentions_offline and mentions_online_fallback:
        return "hybrid"
    if mentions_offline:
        return "offline"
    reqs = {re.split(r"[<>=;\[\s]", r)[0].strip().lower() for r in requires_dist}
    if reqs & ONLINE_LIBS:
        return "online"
    return None


def infer_category(tags):
    for t in tags:
        label = CATEGORY_TAGS.get(t.lower())
        if label:
            return label
    return "Other"


def type_group(component_type):
    """Top-level grouping for the type filter/grid hierarchy - Skill
    / Plugin / Tool, with everything that isn't specifically a Skill
    or a Tool (OCP/TTS/STT/Persona/Pipeline/etc) bucketed as Plugin,
    since all of those are registered via OVOS's plugin-manager
    entry-points mechanism the same way, architecturally."""
    if component_type == "Skill":
        return "Skill"
    if component_type == "Tool":
        return "Tool"
    return "Plugin"


def normalize_tags(value):
    """Coerces a tags value to a list of strings. Defensive fix for
    real-world data quality: ovos-skill-laugh and ovos-skill-
    randomness's actual skill.json files declare "tags" as a single
    string ("ovos skill voice assistant") rather than an array -
    passed through unmodified, this crashed the frontend's
    tags.map() call on live data. A space-separated string is split
    into individual tags as the most likely intended meaning;
    anything else that isn't already a list falls back to empty."""
    if isinstance(value, list):
        return [str(v) for v in value]
    if isinstance(value, str):
        return value.split()
    return []


def days_since(iso_timestamp):
    if not iso_timestamp:
        return None
    try:
        dt = datetime.fromisoformat(iso_timestamp.replace("Z", "+00:00"))
        return (datetime.now(timezone.utc) - dt).days
    except Exception:
        return None


def build_entry(full_name, repo, skill_json, tier, component_type, package_name_override, store_package_names):
    owner, name = full_name.split("/", 1)

    # Fetched once, used for two things below: a description
    # fallback when skill.json/GitHub's About field are both empty,
    # AND setup-section extraction - attempted for EVERY entry
    # regardless of whether a description already exists, since a
    # Skill with its own skill.json description can still have real
    # README setup notes (mycroft.conf changes, systemd services,
    # etc) a generic `pip install X` command can't capture.
    readme_text = fetch_readme(full_name)

    if skill_json is not None:
        package_name = skill_json.get("package_name")
        description = skill_json.get("description")
        tags = normalize_tags(skill_json.get("tags", []))
        display_name = skill_json.get("name") or name
        examples = skill_json.get("examples", [])
        icon = skill_json.get("icon")
        skill_id = skill_json.get("skill_id")
    else:
        package_name = package_name_override
        description = repo.get("description") or ""
        if not description:
            description = extract_readme_description(readme_text)
        tags = normalize_tags(repo.get("topics") or [])
        display_name = name
        examples = []
        icon = None
        skill_id = None

    setup_notes = extract_readme_setup_sections(readme_text)

    version, requires_dist, pypi_release_date = pypi_info(package_name)
    github_release = latest_github_release(full_name)

    license_info = repo.get("license") or {}
    license_id = license_info.get("spdx_id")

    pushed_at = repo.get("pushed_at")
    repo_created_at = repo.get("created_at")
    # last_updated favors the PyPI release date over the repo's own
    # push timestamp when both exist, since a fresh PyPI release is a
    # more deliberate "this changed for users" signal than an
    # arbitrary commit push (which could be a README typo fix).
    last_updated = pypi_release_date or pushed_at

    return {
        "id": full_name.replace("/", "-"),
        "skill_id": skill_id,
        "name": display_name,
        "description": description,
        "examples": examples,
        "tags": tags,
        "category": infer_category(tags),
        "icon": icon,
        "source": repo.get("html_url"),
        "package_name": package_name,
        "pypi_version": version,
        "license": license_id,
        "author": owner,
        "tier": tier,
        "component_type": component_type,
        "type_group": type_group(component_type),
        "stars": repo.get("stargazers_count", 0),
        "forks": repo.get("forks_count", 0),
        "open_issues": repo.get("open_issues_count", 0),
        "on_pypi": version is not None,
        "has_release": github_release is not None,
        "in_ovos_store": package_name in store_package_names if package_name else False,
        "pipeline": extract_pipeline(description),
        "connectivity": classify_connectivity(description, requires_dist),
        "requires_api_key": fetch_requires_api_key(full_name),
        "setup_notes": setup_notes,
        "repo_created_at": repo_created_at,
        "last_updated": last_updated,
        # Two DIFFERENT kinds of "new", deliberately not collapsed
        # into one flag (an earlier version conflated these, which
        # was ambiguous about what "new" even meant): a genuinely new
        # addition to the ecosystem (the repo itself is young) is a
        # different, more noteworthy thing than an existing,
        # long-running project simply having a fresh release.
        "is_new_repo": (days_since(repo_created_at) or 9999) <= 30,
        "is_recently_updated": (days_since(last_updated) or 9999) <= 30,
    }


def main():
    SKILLS_DIR.mkdir(exist_ok=True)
    DOCS_DIR.mkdir(exist_ok=True)
    ignore_list = load_ignore_list()

    print("Discovering via code search (skill.json + pip_spec)...")
    with_skill_json = search_code_repos("filename:skill.json+pip_spec")
    print(f"  {len(with_skill_json)} repos")

    print("Discovering via topic search (ovos, openvoiceos)...")
    topic_repos = search_topic_repos("ovos") | search_topic_repos("openvoiceos")
    print(f"  {len(topic_repos)} repos")

    all_candidates = sorted((with_skill_json | topic_repos) - ignore_list)
    print(f"\n{len(all_candidates)} total unique candidates ({len(ignore_list)} ignored)")

    store_package_names = fetch_ovos_store_package_names()

    entries = []
    for i, full_name in enumerate(all_candidates):
        if i > 0 and i % 20 == 0:
            # Proactive pacing, not just reactive retry - spreads out
            # the burst of API calls this loop makes (repo info +
            # skill.json + possibly __init__.py/setup.py/settingsmeta
            # per candidate) so we're less likely to trip GitHub's
            # secondary rate limit in the first place. A short pause
            # every 20 candidates, not every single one, to keep the
            # weekly run's total time reasonable.
            time.sleep(3)

        repo = repo_info(full_name)
        if repo is None:
            print(f"  SKIP {full_name}: repo not accessible")
            continue
        owner_lower = full_name.split("/", 1)[0].lower()
        if repo.get("fork") and owner_lower not in TRUSTED_FORK_OWNERS:
            # "Is a fork" alone isn't reliable - see
            # TRUSTED_FORK_OWNERS's comment. Skipped only for
            # accounts NOT already confirmed as first-party OVOS
            # ecosystem orgs, to avoid pulling in random personal
            # test-forks while still keeping e.g. OpenVoiceOS's own
            # never-detached forks of their Mycroft predecessors.
            print(f"  SKIP {full_name}: is a fork (untrusted owner)")
            continue
        # No license exclusion - included regardless, with an
        # explicit "No license" badge in the UI (build_entry's
        # license field is simply null). Goal is maximal inclusion,
        # marking what's missing rather than gatekeeping on it.

        skill_json = fetch_skill_json(full_name)
        component_type = None
        package_name_override = None
        # Tracks whether a FORMAL manifest was found for this
        # candidate's type (skill.json, or a declared entry-points
        # group) - not just whether SOME plausible type label was
        # derived. This distinguishes "confirmed, just needs release
        # cleanup" (tier 1/2) from "no formal declaration at all,
        # best-effort guess" (tier 3) - previously every non-skill.json
        # entry was force-tier-3 even when it had a perfectly real,
        # declared entry-points group, which understated plugins with
        # genuinely complete packaging just as much as skills.
        has_confirmed_manifest = False

        if skill_json is not None:
            component_type = "Skill"
            has_confirmed_manifest = True
        else:
            if full_name not in topic_repos:
                # Found only via the skill.json search but the file
                # vanished/moved since - and it's not topic-tagged
                # either, so there's no fallback signal to trust.
                print(f"  SKIP {full_name}: skill.json missing, not topic-tagged")
                continue
            # One fetch of setup.py/pyproject.toml, reused for both
            # entry-point-group detection and package-name guessing -
            # see fetch_setup_and_pyproject()'s docstring for why this
            # replaced two separate functions that each fetched the
            # same two files independently.
            setup_text, pyproject_text = fetch_setup_and_pyproject(full_name)
            package_name_override = derive_package_name(setup_text, pyproject_text)
            entry_point_groups = derive_entry_point_groups(setup_text, pyproject_text)
            component_type = derive_component_type(entry_point_groups)
            if component_type is not None:
                has_confirmed_manifest = True
            else:
                # No declared entry-points group either - last-resort
                # signals, in order. Both land at tier 3 regardless of
                # which one matched, since neither is a formal
                # declaration the way skill.json/entry-points are.
                if looks_like_skill_code(full_name):
                    component_type = "Skill"
                elif package_name_override:
                    # A real installable package (setup.py/pyproject.toml
                    # declares a name=) with no skill/plugin-specific
                    # signal at all - catches CLI clients, helper
                    # libraries, and other genuinely OVOS-adjacent
                    # tools that aren't skills or plugins. Previously
                    # excluded outright for not matching skill-code
                    # signs specifically.
                    component_type = "Tool"
                else:
                    print(f"  SKIP {full_name}: topic-tagged but no plugin/skill/tool signs found")
                    continue

        entry = build_entry(
            full_name, repo, skill_json, tier=3,
            component_type=component_type, package_name_override=package_name_override,
            store_package_names=store_package_names,
        )
        if has_confirmed_manifest:
            entry["tier"] = 1 if (entry["on_pypi"] and entry["has_release"]) else 2
        if entry["in_ovos_store"]:
            # Official Store inclusion means a real OVOS maintainer
            # reviewed and approved this - a STRONGER completeness
            # signal than PyPI+release, since the store doesn't
            # require either (many OVOS skills install straight from
            # source, not PyPI). Without this override, a skill could
            # be reviewed, approved, and actively used via the
            # official store while this site badged it "Incomplete" -
            # a real, confusing contradiction found by inspection.
            # The underlying "Not on PyPI"/"No release" badges still
            # show independently as plain facts either way.
            entry["tier"] = 1
        # else: stays tier 3 (last-resort fallback, no formal manifest)

        entries.append(entry)

        out_name = full_name.replace("/", "-") + ".json"
        with open(SKILLS_DIR / out_name, "w") as f:
            json.dump(entry, f, indent=2)
            f.write("\n")

        tier_note = f" [tier {entry['tier']}]"
        type_note = f" [{entry['component_type']}]"
        pypi_note = "" if entry["on_pypi"] else " [not on PyPI]"
        release_note = "" if entry["has_release"] else " [no release]"
        print(f"  OK   {full_name}{tier_note}{type_note}{pypi_note}{release_note}")

    entries.sort(key=lambda e: (e["name"] or "").lower())
    with open(FEED_PATH, "w") as f:
        json.dump(entries, f, indent=2)
        f.write("\n")

    meta = {
        "total_candidates_reviewed": len(all_candidates),
        "total_entries_included": len(entries),
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    with open(META_PATH, "w") as f:
        json.dump(meta, f, indent=2)
        f.write("\n")

    print(f"\nWrote {len(entries)} entries to {SKILLS_DIR} and {FEED_PATH}")


if __name__ == "__main__":
    main()
