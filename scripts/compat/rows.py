"""Fetch the source a level 3 run needs: the skill's repo at the git tag of
the version under test, its golden files, and (via generated.py) generated
rows from the same checkout.

Only the tag of the tested version is used. A release's golden files and
intent files describe that release; rows from the default branch could name
intents the tested version does not have and would report false misses. A
version without a matching tag, or a tag without golden files, simply has no
golden run (it may still get a generated one).

Runs in the secret-less test job: anonymous HTTPS clones, no token.
"""
import re
import subprocess
from pathlib import Path

GOLDEN_GLOB = "golden_utterances*.jsonl"
GOLDEN_DIR = Path("test") / "end2end"


def _git(args, timeout=120, cwd=None):
    return subprocess.run(["git", *args], capture_output=True, text=True, timeout=timeout,
                          cwd=cwd, env={"GIT_TERMINAL_PROMPT": "0", "PATH": "/usr/bin:/bin"})


def find_tag(repo_url, version):
    """The tag for `version`: v1.2.3, 1.2.3 or V1.2.3; None when absent."""
    try:
        proc = _git(["ls-remote", "--tags", "--refs", repo_url], timeout=60)
    except subprocess.TimeoutExpired:
        return None
    if proc.returncode != 0:
        return None
    tags = {line.rsplit("refs/tags/", 1)[-1] for line in proc.stdout.splitlines() if "refs/tags/" in line}
    for cand in (f"v{version}", version, f"V{version}", f"release-{version}"):
        if cand in tags:
            return cand
    # pypi normalises 0.2.0a1 -> tags sometimes read 0.2.0-alpha.1 etc.; match
    # on the numeric core only when exactly one tag shares it with the same suffix.
    norm = re.sub(r"[^0-9a-z]", "", version.lower())
    hits = [t for t in tags if re.sub(r"[^0-9a-z]", "", t.lower().lstrip("v")) == norm]
    return hits[0] if len(hits) == 1 else None


def checkout(repo_url, version, dest):
    """Shallow-clone the version's tag into dest. Returns (tag, reason)."""
    tag = find_tag(repo_url, version)
    if not tag:
        return None, f"no git tag for version {version}"
    try:
        proc = _git(["clone", "-q", "--depth", "1", "--branch", tag, repo_url, str(dest)], timeout=300)
    except subprocess.TimeoutExpired:
        return None, "git clone timed out"
    if proc.returncode != 0:
        return None, "git clone failed: " + (proc.stderr.strip().splitlines() or ["?"])[-1][:200]
    return tag, None


def golden_files(dest):
    d = Path(dest) / GOLDEN_DIR
    return sorted(str(p) for p in d.glob(GOLDEN_GLOB)) if d.is_dir() else []
