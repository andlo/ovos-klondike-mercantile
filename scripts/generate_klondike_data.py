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
  (skill.json for Skills, a declared entry-points group for Plugins,
  or a setup.py/pyproject.toml name= declaration for Tools),
  published on PyPI, has a GitHub release.
- Tier 2 (Incomplete): has a confirmed manifest, but missing a PyPI
  release and/or a GitHub release - shown with an explicit "not on
  PyPI" / "no release" badge rather than excluded.
- Tier 3 (Inferred, Unconfirmed): NO formal manifest found at all -
  specifically, skill-shaped __init__.py code (OVOSSkill/
  FallbackSkill/etc) with no skill.json and no setup.py/pyproject.toml
  name= either, guessed as "Skill" purely from behavior. A
  topic-tagged repo matching none of these is excluded outright - the
  topic alone isn't proof of anything.
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
STATE_PATH = ROOT / "state.json"
OVOS_STORE_FEED_URL = "https://openvoiceos.github.io/OVOS-skills-store/skills.json"
IGNORE_LIST_PATH = ROOT / "ignore.txt"

# How many ALREADY-KNOWN candidates get refreshed per run, rotating
# through the full list over several runs rather than reprocessing
# everyone every time - see main()'s docstring-length comment for
# why. Genuinely NEW candidates (first time seen) are always
# processed in full regardless of this number, every run.
BATCH_SIZE = 60

# Cap on genuinely NEW candidates processed per run - previously
# uncapped ("every new candidate, every run"), which was safe while
# discovery found a few new repos per run at most. Adding the
# ovos-in-name search signal jumped the candidate pool from ~360 to
# ~2000 in one step - without a cap, that first run alone would try
# to process ~1700 "new" candidates at once, right back into the
# same rate-limit trouble BATCH_SIZE was built to solve for known
# candidates. New candidates beyond this cap simply wait for the
# next run instead - they're still "new" then too, so nothing is
# lost, just spread out.
NEW_BATCH_SIZE = 60

PROVIDER_PATTERN = re.compile(r"provider for ([\w.-]+)", re.IGNORECASE)
ONLINE_LIBS = {"requests", "bs4", "beautifulsoup4", "feedparser", "aiohttp", "httpx"}
# zeroconf is the standard mDNS/LAN-discovery library used across the
# OVOS ecosystem for exactly this purpose - confirmed directly:
# andlo/ovos-skill-intercom's own requirements.txt declares nothing
# but "zeroconf".
LAN_LIBS = {"zeroconf"}

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
    """Two kinds of lines, both from ignore.txt: "owner/repo"
    excludes exactly that repo; a bare "owner" (no slash) excludes
    every repo from that whole account/org - added after direct
    community feedback (a core OVOS contributor) recommending
    against including OVOSHatchery's repos wholesale ("that org is
    literally a dumpster of broken stuff"), which only became a real
    concern once the ovos-in-name discovery signal started actually
    surfacing repos from it. Returns (exact_repo_set, blocked_owner_set)."""
    if not IGNORE_LIST_PATH.exists():
        return set(), set()
    lines = IGNORE_LIST_PATH.read_text().splitlines()
    entries = {ln.strip() for ln in lines if ln.strip() and not ln.strip().startswith("#")}
    exact = {e for e in entries if "/" in e}
    owners = {e.lower() for e in entries if "/" not in e}
    return exact, owners


def load_state():
    """Rotation position + the set of candidates ever ATTEMPTED
    before (whether they became an entry or were deliberately
    skipped - fork/no-manifest/etc). Deliberately NOT the same as
    "has an entry in previous_entries": a candidate that was
    correctly excluded (untrusted fork, no skill/plugin signal) has
    no entry, but re-treating it as "new" every single run would
    mean it gets reprocessed every run forever, defeating the whole
    point of batching - caught by inspection: with ~305 successful
    entries out of ~356 candidates, the ~51 legitimately-skipped ones
    were silently costing a full extra pass every run before this
    field existed. A fresh repo (no prior state.json) starts empty."""
    if not STATE_PATH.exists():
        return {"cursor": 0, "attempted": []}
    try:
        state = json.loads(STATE_PATH.read_text())
        state.setdefault("cursor", 0)
        state.setdefault("attempted", [])
        return state
    except Exception:
        return {"cursor": 0, "attempted": []}


def save_state(state):
    STATE_PATH.write_text(json.dumps(state, indent=2) + "\n")


def load_previous_entries():
    """Previous run's output, keyed by id - the merge base for this
    run: candidates NOT selected for reprocessing keep this data
    unchanged rather than needing a full sweep every run."""
    if not FEED_PATH.exists():
        return {}
    try:
        data = json.loads(FEED_PATH.read_text())
        return {e["id"]: e for e in data if "id" in e}
    except Exception:
        return {}


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


def search_name_repos(keyword):
    """Repos with the keyword literally in their own name -
    complements the topic-search signal for repos that never got a
    GitHub topic set at all (found by inspection: several real
    OpenVoiceOS repos, including ovos-control-panel, have zero
    topics AND no skill.json, making them invisible to both other
    discovery signals despite genuinely being OVOS tools). Also
    fork:true for the same reason as search_topic_repos - GitHub
    excludes forks from repository search by default."""
    names = set()
    page = 1
    while True:
        items = gh_json(
            "api", f"search/repositories?q={keyword}+in:name+fork:true&per_page=100&page={page}"
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


def fetch_settings_fields(full_name):
    """Parses settingsmeta.json's real structure (skillMetadata ->
    sections -> fields, confirmed by inspecting a real one) into a
    list of {name, type, label} dicts - one per actual configurable
    setting. Pure informational "label"-type fields (explanatory
    text with no "name", used to describe a section rather than
    configure anything) are skipped, since they aren't settings
    themselves. Returns an empty list if there's no settingsmeta.json
    or it doesn't parse - deliberately tolerant, since the exact
    shape varies enough across skills that a strict parser would
    silently miss real ones."""
    text = fetch_file(full_name, "settingsmeta.json")
    if text is None:
        return []
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return []
    fields = []
    sections = (data.get("skillMetadata") or {}).get("sections") or []
    for section in sections:
        for field in section.get("fields") or []:
            name = field.get("name")
            if not name:
                continue
            fields.append({
                "name": name,
                "type": field.get("type"),
                "label": field.get("label") or name,
            })
    return fields


def requires_api_key_from_settings(settings_fields):
    """Whether any real setting field (see fetch_settings_fields)
    looks like it wants an API key or credential - checked by name/
    label content, not a blind text search over the whole file (a
    label-only field could mention "API key" in prose without there
    being an actual field for it, and vice versa)."""
    keywords = ("api_key", "api key", "apikey", "token", "secret", "password", "credential")
    for f in settings_fields:
        haystack = f"{f['name']} {f['label']}".lower()
        if any(k in haystack for k in keywords):
            return True
    return False


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
            # Strip markdown code-FENCE marker lines (```, ```bash,
            # etc) - content is shown as plain preformatted text, not
            # rendered markdown, so the bare fence markers just show
            # up literally in the output and look broken rather than
            # adding anything.
            body = "\n".join(
                ln for ln in body.splitlines()
                if not re.match(r"^\s*```\w*\s*$", ln)
            ).strip()
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


OVOS_LOCALIZE_SKILLS_URL = "https://raw.githubusercontent.com/OpenVoiceOS/ovos-localize/dev/skills.txt"


def fetch_ovos_localize_tracked_repos():
    """Plain-text "owner/repo" list (one per line, "#"-comments
    allowed) of repos the official OVOS Localize translation
    platform tracks - fetched via a plain HTTP GET, same as
    fetch_ovos_store_package_names(), so it costs nothing against
    GitHub's API rate limit regardless of how many entries this
    script processes."""
    try:
        with urllib.request.urlopen(OVOS_LOCALIZE_SKILLS_URL, timeout=10) as resp:
            text = resp.read().decode("utf-8", errors="ignore")
        return {
            line.strip() for line in text.splitlines()
            if line.strip() and not line.strip().startswith("#")
        }
    except Exception:
        return set()


LOCALE_DIR_PATTERN = re.compile(r"^[a-z]{2}(-[a-zA-Z]{2,})?$")


def fetch_locale_languages(full_name):
    """Lists the locale/ directory to find which language codes a
    Skill supports (e.g. ["en-us", "da-dk"]) - only called for
    component_type == "Skill" entries, since plugins/tools don't
    follow this convention in practice (confirmed by inspection
    across this whole ecosystem: locale/<lang>/ is specifically the
    Skill packaging convention). Returns an empty list if there's no
    locale/ directory, or the repo isn't a Skill.

    Normalized to lowercase - different repos' locale/ folders use
    inconsistent casing (en-us vs en-US), which without this showed
    up as confusing duplicate entries in the language filter
    dropdown ("en-US" and "en-us" as two separate options)."""
    data = gh_ok("api", f"repos/{full_name}/contents/locale")
    if not data:
        return []
    return sorted(set(
        item["name"].lower() for item in data
        if item.get("type") == "dir" and LOCALE_DIR_PATTERN.match(item["name"])
    ))


def extract_pipeline(description):
    if not description:
        return None
    match = PROVIDER_PATTERN.search(description)
    return match.group(1).rstrip(".") if match else None


def classify_connectivity(description, requires_dist, requirements_text=""):
    """Returns "offline", "lan", "hybrid", "online", or None. "lan"
    is checked FIRST and wins over a plain "offline" claim when both
    are present - found by inspection: andlo/ovos-skill-intercom's
    own description says both "fully offline, no internet needed"
    AND "LAN intercom... same local network", and "LAN" is the more
    informative of the two (it still needs networking, just not the
    internet - a genuinely different thing than a skill that uses no
    network at all, which "offline" alone doesn't distinguish).

    Falls back, in order, to declared dependencies when the
    description doesn't address connectivity at all: PyPI's
    requires_dist first, then the repo's own requirements.txt
    (checked second, and only fetched by the caller when the
    description+PyPI check was inconclusive, to avoid an extra API
    call for every single entry) - catches cases requires_dist alone
    misses, e.g. a package not yet on PyPI (so requires_dist is
    empty) that still declares real dependencies in its own repo."""
    desc_lower = (description or "").lower()
    mentions_lan = bool(
        re.search(r"\blan\b|local network|same network|mdns|multicast", desc_lower)
    )
    if mentions_lan:
        return "lan"
    mentions_offline = bool(re.search(r"\boffline\b|\bno internet\b", desc_lower))
    mentions_online_fallback = bool(
        re.search(r"online fallback|optional.*online|fallback.*online", desc_lower)
    )
    if mentions_offline and mentions_online_fallback:
        return "hybrid"
    if mentions_offline:
        return "offline"

    def pkg_names(lines):
        return {re.split(r"[<>=;\[\s]", ln)[0].strip().lower() for ln in lines if ln.strip()}

    reqs = pkg_names(requires_dist)
    if reqs & LAN_LIBS:
        return "lan"
    if reqs & ONLINE_LIBS:
        return "online"

    if requirements_text:
        req_pkgs = pkg_names(requirements_text.splitlines())
        if req_pkgs & LAN_LIBS:
            return "lan"
        if req_pkgs & ONLINE_LIBS:
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


def build_entry(full_name, repo, skill_json, tier, component_type, package_name_override, store_package_names, localize_tracked_repos):
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
        # Three-tier fallback when skill.json omits package_name:
        # 1) skill.json's own declaration (most authoritative, when
        #    present); 2) setup.py/pyproject.toml's own name= field,
        #    per direct advice from JarbasAI (OVOS core contributor)
        #    on exactly this question - more reliable than guessing,
        #    since a repo's name doesn't always match its actual
        #    PyPI package name; 3) the repo's own bare name as a
        #    last resort (works often enough in practice - found by
        #    inspection: OpenVoiceOS/ovos-skill-date-time's skill.json
        #    has no package_name field at all, but the package IS
        #    published on PyPI under exactly the repo's own name).
        package_name = skill_json.get("package_name") or package_name_override or name
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

    # Fetched for both Skills and Plugins (unlike locale/languages
    # below, which is Skill-only) - plugins commonly have real
    # configurable settings too (API keys, endpoints, etc).
    settings_fields = fetch_settings_fields(full_name)

    # Locale/language listing is only meaningful for Skills - see
    # fetch_locale_languages()'s docstring. Skipped entirely for
    # Plugins/Tools rather than making a call that would almost
    # always come back empty.
    languages = fetch_locale_languages(full_name) if component_type == "Skill" else []

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

    # Try the cheap check first (description + PyPI's already-fetched
    # requires_dist, no extra call); only fetch requirements.txt as a
    # second pass when that came back inconclusive, so this doesn't
    # cost an API call for every single entry - most already resolve
    # from the description or PyPI metadata alone.
    connectivity = classify_connectivity(description, requires_dist)
    if connectivity is None:
        requirements_text = fetch_file(full_name, "requirements.txt") or ""
        connectivity = classify_connectivity(description, requires_dist, requirements_text)

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
        "archived": bool(repo.get("archived")),
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
        "connectivity": connectivity,
        "requires_api_key": requires_api_key_from_settings(settings_fields),
        "settings_fields": settings_fields,
        "setup_notes": setup_notes,
        "languages": languages,
        "in_ovos_localize": full_name in localize_tracked_repos,
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
    """Runs discovery every time (cheap - a few dozen search-API
    calls total), but only fully FETCHES/PROCESSES a bounded subset
    of candidates per run:
    - Up to NEW_BATCH_SIZE genuinely NEW candidates (never attempted
      before) - so new repos are still caught quickly, but a sudden
      jump in the candidate pool (e.g. a new discovery signal) can't
      flood a single run uncapped either.
    - Up to BATCH_SIZE ALREADY-KNOWN candidates, rotating through
      the full known list a chunk at a time via state.json's cursor,
      so existing entries get refreshed periodically without every
      run needing to touch all ~350+ of them.

    Found the hard way today: processing everyone in one run made
    each run take 15-25+ minutes and made a real, repeated dent in
    the hourly rate-limit budget once README/setup-section/locale-
    listing calls were added per candidate. Batching keeps each run
    small enough to run much more often (see the workflow's cron)
    while still fully cycling through the known list over several
    runs, and lets candidates NOT reprocessed this run simply keep
    their previous data instead of needing to be re-fetched from
    scratch to appear in the feed at all.
    """
    SKILLS_DIR.mkdir(exist_ok=True)
    DOCS_DIR.mkdir(exist_ok=True)
    ignore_exact, ignore_owners = load_ignore_list()
    state = load_state()
    previous_entries = load_previous_entries()

    print("Discovering via code search (skill.json + pip_spec)...")
    with_skill_json = search_code_repos("filename:skill.json+pip_spec")
    print(f"  {len(with_skill_json)} repos")

    print("Discovering via topic search (ovos, openvoiceos)...")
    topic_repos = search_topic_repos("ovos") | search_topic_repos("openvoiceos")
    print(f"  {len(topic_repos)} repos")

    print("Discovering via name search (ovos in repo name)...")
    name_repos = search_name_repos("ovos")
    print(f"  {len(name_repos)} repos")

    # A repo found via EITHER topic or name search gets the same
    # trust for the entry-points/skill-code/tool fallback path below -
    # both are similarly strong "this really is OVOS-related" signals,
    # not just an accident of being near the word "OVOS" somewhere.
    topic_or_name_repos = topic_repos | name_repos

    all_candidates = sorted(
        (with_skill_json | topic_or_name_repos) - ignore_exact
        - {c for c in (with_skill_json | topic_or_name_repos)
           if c.split("/", 1)[0].lower() in ignore_owners}
    )
    print(
        f"\n{len(all_candidates)} total unique candidates "
        f"({len(ignore_exact)} repos ignored, {len(ignore_owners)} owners blocked)"
    )

    attempted_ids = set(state.get("attempted", []))
    all_new_candidates = [c for c in all_candidates if c.replace("/", "-") not in attempted_ids]
    known_candidates = [c for c in all_candidates if c.replace("/", "-") in attempted_ids]

    # Capped, not "every new candidate every run" - see
    # NEW_BATCH_SIZE's comment. Anything beyond the cap is simply
    # left for the next run(s), still new then too.
    new_candidates = all_new_candidates[:NEW_BATCH_SIZE]
    remaining_new = len(all_new_candidates) - len(new_candidates)

    cursor = state.get("cursor", 0)
    if known_candidates:
        cursor = cursor % len(known_candidates)
        batch = known_candidates[cursor:cursor + BATCH_SIZE]
        if len(batch) < BATCH_SIZE:
            batch += known_candidates[:BATCH_SIZE - len(batch)]
    else:
        batch = []

    to_process = new_candidates + batch
    print(
        f"Processing {len(to_process)} this run "
        f"({len(new_candidates)} new"
        + (f", {remaining_new} more new waiting for later runs" if remaining_new else "")
        + f", {len(batch)} refreshed from rotation "
        f"of {len(known_candidates)} known)"
    )

    store_package_names = fetch_ovos_store_package_names()
    localize_tracked_repos = fetch_ovos_localize_tracked_repos()

    merged_entries = dict(previous_entries)  # everyone starts carried-over

    for i, full_name in enumerate(to_process):
        if i > 0 and i % 20 == 0:
            # Proactive pacing, not just reactive retry - spreads out
            # the burst of API calls this loop makes (repo info +
            # skill.json + possibly __init__.py/setup.py/settingsmeta/
            # README/locale per candidate) so we're less likely to
            # trip GitHub's secondary rate limit in the first place.
            time.sleep(3)

        attempted_ids.add(full_name.replace("/", "-"))
        repo = repo_info(full_name)
        if repo is None:
            print(f"  SKIP {full_name}: repo not accessible")
            merged_entries.pop(full_name.replace("/", "-"), None)
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
            merged_entries.pop(full_name.replace("/", "-"), None)
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
            # A repo can be BOTH a skill.json-listed Skill AND a
            # registered ovos-plugin-manager plugin at the same time
            # - found by inspection: andlo/ovos-common-reading-
            # pipeline-plugin has a skill.json but its setup.py
            # explicitly declares entry_points={"opm.pipeline": ...},
            # a genuine pipeline-plugin registration that was being
            # silently ignored since this branch never checked for
            # it. Entry-points registration is the more
            # architecturally precise signal for what kind of
            # runtime component something actually IS, so it
            # overrides the "Skill" default when present.
            setup_text, pyproject_text = fetch_setup_and_pyproject(full_name)
            entry_point_groups = derive_entry_point_groups(setup_text, pyproject_text)
            plugin_type = derive_component_type(entry_point_groups)
            if plugin_type is not None and plugin_type != "Skill":
                component_type = plugin_type
            # Package-name fallback when skill.json doesn't declare
            # one - per direct advice from JarbasAI (OVOS core
            # contributor) in response to this exact question: "If
            # there's a setup.py or pyproject.toml you get package
            # name from there and check if it's on pypi". More
            # reliable than guessing from the bare repo name (which
            # build_entry() still falls back to if this comes up
            # empty too) - a repo's name doesn't always match its
            # actual PyPI package name, but its own setup.py/
            # pyproject.toml declaration does.
            package_name_override = derive_package_name(setup_text, pyproject_text)
        else:
            if full_name not in topic_or_name_repos:
                # Found only via the skill.json search but the file
                # vanished/moved since - and it's neither topic-
                # tagged nor name-matched either, so there's no
                # fallback signal to trust.
                print(f"  SKIP {full_name}: skill.json missing, not topic/name-matched")
                merged_entries.pop(full_name.replace("/", "-"), None)
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
                # signals. The two are NOT equally strong though:
                # skill-shaped __init__.py code is a real guess (no
                # declaration anywhere says "this is a skill"), but a
                # genuine setup.py/pyproject.toml name= declaration
                # IS a formal manifest for a Tool the same way
                # skill.json is for a Skill - found by inspection:
                # andlo/ovos-tui-client is on PyPI with a real GitHub
                # release, every signal pointing at "Looks Complete",
                # but was stuck at tier 3 forever because this branch
                # never set has_confirmed_manifest for the Tool case,
                # unlike the Skill/Plugin cases above.
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
                    has_confirmed_manifest = True
                else:
                    print(f"  SKIP {full_name}: topic-tagged but no plugin/skill/tool signs found")
                    merged_entries.pop(full_name.replace("/", "-"), None)
                    continue

        entry = build_entry(
            full_name, repo, skill_json, tier=3,
            component_type=component_type, package_name_override=package_name_override,
            store_package_names=store_package_names, localize_tracked_repos=localize_tracked_repos,
        )
        if has_confirmed_manifest:
            entry["tier"] = 1 if (entry["on_pypi"] and entry["has_release"]) else 2
        if entry["in_ovos_store"]:
            # OVOS's own upcoming Skill Store (not yet officially
            # launched) inclusion means a maintainer reviewed and
            # merged this - a STRONGER completeness signal than
            # PyPI+release, since that store doesn't require either
            # (many OVOS skills install straight from source, not
            # PyPI). Without this override, a skill could be
            # reviewed, merged, and actively used there while this
            # site badged it "Incomplete" - a real, confusing
            # contradiction found by inspection. The underlying
            # "Not on PyPI"/"No release" badges still show
            # independently as plain facts either way.
            entry["tier"] = 1
        # else: stays tier 3 (last-resort fallback, no formal manifest)

        merged_entries[entry["id"]] = entry

        tier_note = f" [tier {entry['tier']}]"
        type_note = f" [{entry['component_type']}]"
        pypi_note = "" if entry["on_pypi"] else " [not on PyPI]"
        release_note = "" if entry["has_release"] else " [no release]"
        print(f"  OK   {full_name}{tier_note}{type_note}{pypi_note}{release_note}")

    # Drop entries for candidates that no longer appear at all
    # (deleted, made private, or now in ignore.txt) - checked against
    # the full current candidate list, not just what got reprocessed
    # this run, so stale entries don't linger indefinitely just
    # because their rotation slot hasn't come up again yet.
    valid_ids = {c.replace("/", "-") for c in all_candidates}
    merged_entries = {k: v for k, v in merged_entries.items() if k in valid_ids}

    # Retroactively normalize language codes to lowercase across
    # EVERY entry, not just ones reprocessed this run - fixes the
    # en-US/en-us duplicate-option problem immediately for
    # carried-over entries too, rather than waiting for each one's
    # rotation turn to come up again (could be several runs away).
    for entry in merged_entries.values():
        if entry.get("languages"):
            entry["languages"] = sorted(set(lang.lower() for lang in entry["languages"]))

    entries = sorted(merged_entries.values(), key=lambda e: (e["name"] or "").lower())
    for entry in entries:
        out_name = entry["id"] + ".json"
        with open(SKILLS_DIR / out_name, "w") as f:
            json.dump(entry, f, indent=2)
            f.write("\n")
    # Remove skill/*.json files for anything no longer valid, so
    # stale per-entry files don't accumulate forever.
    for path in SKILLS_DIR.glob("*.json"):
        if path.stem not in valid_ids:
            path.unlink()

    with open(FEED_PATH, "w") as f:
        json.dump(entries, f, indent=2)
        f.write("\n")

    new_cursor = (cursor + len(batch)) % len(known_candidates) if known_candidates else 0
    # Only keep attempted-ids for candidates still actually valid -
    # a repo that's gone (deleted/private/now ignored) shouldn't
    # keep occupying a rotation slot forever.
    save_state({
        "cursor": new_cursor,
        "attempted": sorted(attempted_ids & valid_ids),
    })

    meta = {
        "total_candidates_reviewed": len(all_candidates),
        "total_entries_included": len(entries),
        "processed_this_run": len(to_process),
        "new_candidates_processed_this_run": len(new_candidates),
        "new_candidates_remaining": remaining_new,
        "known_candidates_count": len(known_candidates),
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    with open(META_PATH, "w") as f:
        json.dump(meta, f, indent=2)
        f.write("\n")

    print(f"\nWrote {len(entries)} entries to {SKILLS_DIR} and {FEED_PATH}")


if __name__ == "__main__":
    main()
