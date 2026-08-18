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

Every candidate gets one of three tiers:
- Tier 1 (verified): has skill.json, published on PyPI, has a
  GitHub release.
- Tier 2 (partial): has skill.json, but missing a PyPI release
  and/or a GitHub release - shown with an explicit "not on PyPI" /
  "no release" badge rather than excluded.
- Tier 3 (unverified): NO skill.json found, but the repo is
  topic-tagged as OVOS-related AND its __init__.py shows real signs
  of being an OVOS skill (imports ovos_workshop, subclasses
  OVOSSkill/FallbackSkill, uses @intent_handler, etc.) - metadata is
  inferred from the repo's own description/README/setup.py rather
  than a skill.json, and shown with an "unverified" badge. A
  topic-tagged repo with no such signs at all is excluded outright -
  the topic alone isn't proof it's actually a skill.
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
OVOS_STORE_FEED_URL = "https://openvoiceos.github.io/OVOS-skills-store/skills.json"
IGNORE_LIST_PATH = ROOT / "ignore.txt"

PROVIDER_PATTERN = re.compile(r"provider for ([\w.-]+)", re.IGNORECASE)
ONLINE_LIBS = {"requests", "bs4", "beautifulsoup4", "feedparser", "aiohttp", "httpx"}

# Signs of a real OVOS skill in __init__.py - used only for Tier 3
# candidates (topic-tagged but no skill.json found), to filter out
# repos that merely tag themselves "ovos" without actually being a
# skill (a config repo, a fork with the topic left over, etc.).
SKILL_CODE_SIGNS = (
    "OVOSSkill", "FallbackSkill", "CommonQuerySkill",
    "ovos_workshop", "intent_handler", "create_skill",
)

CATEGORY_TAGS = {
    "education": "Education", "utility": "Utility", "entertainment": "Entertainment",
    "daily": "Daily", "music": "Music", "games": "Games", "productivity": "Productivity",
    "home": "Home", "information": "Information", "news": "News",
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
    names = set()
    page = 1
    while True:
        items = gh_json(
            "api", f"search/repositories?q=topic:{topic}&per_page=100&page={page}"
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
    (deleted/renamed since discovery)."""
    return gh_ok("api", f"repos/{full_name}")


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


def fetch_requires_api_key(full_name):
    text = fetch_file(full_name, "settingsmeta.json")
    if text is None:
        return False
    lowered = text.lower()
    return "api_key" in lowered or "api key" in lowered


def guess_package_name(full_name):
    """Best-effort package_name for a Tier 3 (no skill.json) entry -
    read from setup.py's own name= argument, since that's the actual
    PyPI-facing declaration and more trustworthy than guessing from
    the repo name (which don't always match, e.g. skill-alerts vs
    ovos-skill-alerts)."""
    text = fetch_file(full_name, "setup.py") or ""
    match = re.search(r"""name\s*=\s*["']([\w.-]+)["']""", text)
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


def days_since(iso_timestamp):
    if not iso_timestamp:
        return None
    try:
        dt = datetime.fromisoformat(iso_timestamp.replace("Z", "+00:00"))
        return (datetime.now(timezone.utc) - dt).days
    except Exception:
        return None


def build_entry(full_name, repo, skill_json, tier, store_package_names):
    owner, name = full_name.split("/", 1)

    if skill_json is not None:
        package_name = skill_json.get("package_name")
        description = skill_json.get("description")
        tags = skill_json.get("tags", [])
        display_name = skill_json.get("name") or name
        examples = skill_json.get("examples", [])
        icon = skill_json.get("icon")
        skill_id = skill_json.get("skill_id")
    else:
        package_name = guess_package_name(full_name)
        description = repo.get("description") or ""
        tags = repo.get("topics", [])
        display_name = name
        examples = []
        icon = None
        skill_id = None

    version, requires_dist, pypi_release_date = pypi_info(package_name)
    github_release = latest_github_release(full_name)

    license_info = repo.get("license") or {}
    license_id = license_info.get("spdx_id")

    pushed_at = repo.get("pushed_at")
    last_updated = pypi_release_date or pushed_at

    return {
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
        "on_pypi": version is not None,
        "has_release": github_release is not None,
        "in_ovos_store": package_name in store_package_names if package_name else False,
        "pipeline": extract_pipeline(description),
        "connectivity": classify_connectivity(description, requires_dist),
        "requires_api_key": fetch_requires_api_key(full_name),
        "last_updated": last_updated,
        "is_new": (days_since(last_updated) or 9999) <= 30,
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
        if repo.get("fork"):
            print(f"  SKIP {full_name}: is a fork")
            continue
        if not repo.get("license"):
            print(f"  SKIP {full_name}: no license")
            continue

        skill_json = fetch_skill_json(full_name)

        if skill_json is None:
            if full_name not in topic_repos:
                # Found only via the skill.json search but the file
                # vanished/moved since - and it's not topic-tagged
                # either, so there's no fallback signal to trust.
                print(f"  SKIP {full_name}: skill.json missing, not topic-tagged")
                continue
            if not looks_like_skill_code(full_name):
                print(f"  SKIP {full_name}: topic-tagged but __init__.py shows no skill signs")
                continue

        entry = build_entry(full_name, repo, skill_json, tier=3, store_package_names=store_package_names)
        if skill_json is not None:
            entry["tier"] = 1 if (entry["on_pypi"] and entry["has_release"]) else 2

        entries.append(entry)

        out_name = full_name.replace("/", "-") + ".json"
        with open(SKILLS_DIR / out_name, "w") as f:
            json.dump(entry, f, indent=2)
            f.write("\n")

        tier_note = f" [tier {entry['tier']}]"
        pypi_note = "" if entry["on_pypi"] else " [not on PyPI]"
        release_note = "" if entry["has_release"] else " [no release]"
        print(f"  OK   {full_name}{tier_note}{pypi_note}{release_note}")

    entries.sort(key=lambda e: (e["name"] or "").lower())
    with open(FEED_PATH, "w") as f:
        json.dump(entries, f, indent=2)
        f.write("\n")

    print(f"\nWrote {len(entries)} entries to {SKILLS_DIR} and {FEED_PATH}")


if __name__ == "__main__":
    main()
