# ⛏️ OVOS Klondike Mercantile

A global, automatically-discovered directory of **OVOS skills across
all of GitHub** - not just one author's work. If [andlo's own skills
directory](https://github.com/andlo/ovos-skills-directory) is a
curated personal store, this is the mercantile at the edge of town:
everything that might be gold gets a place on the shelf, clearly
labeled by how sure we are it's the real thing.

**Live site**: [andlo.github.io/ovos-klondike-mercantile](https://andlo.github.io/ovos-klondike-mercantile/)

## How this works

### Discovery

Two independent signals, unioned:

1. **Code search** for `skill.json` files containing `pip_spec` -
   found by testing several candidate search terms against real
   results. `skill_id` alone matched unrelated projects (an RPG
   skill-tree app, a notes repo) since that term isn't distinctive
   enough on its own; `pip_spec` reliably matched only genuine OVOS
   skill.json files, across several different authors and orgs.
2. **Topic search** for repos tagged `ovos` or `openvoiceos` on
   GitHub - catches skills that exist but weren't found by signal 1
   (missing skill.json, misplaced, or not written yet).

### Tiers

Every entry is one of three tiers, shown as a badge:

- **Verified** (tier 1): has a `skill.json`, published on PyPI, has
  a GitHub release.
- **Partial** (tier 2): has a `skill.json`, but is missing a PyPI
  release and/or a GitHub release - shown with an explicit
  "Not on PyPI" / "No release" badge rather than excluded. The goal
  is to include as much as possible, not gatekeep on publishing
  status.
- **Unverified** (tier 3): **no** `skill.json` found, but the repo
  is topic-tagged as OVOS-related AND its `__init__.py` shows real
  signs of being an OVOS skill (imports `ovos_workshop`, subclasses
  `OVOSSkill`/`FallbackSkill`, uses `@intent_handler`, etc.).
  Metadata (name, description, tags) is inferred from the repo's own
  GitHub description/topics/`setup.py` rather than a proper
  `skill.json`, and shown with dashed card borders plus an
  "Unverified" badge. A topic-tagged repo with **no** such code
  signs at all is excluded outright - the topic alone isn't proof.

### Cross-referencing

Each entry is checked against:
- **PyPI** - latest version, release date, and dependencies (the
  latter feeds the offline/hybrid/online badge - see below).
- **The official [OVOS Skill Store](https://openvoiceos.github.io/OVOS-skills-store/)** -
  entries already listed there get an "OVOS Store" badge.
- **`settingsmeta.json`** - a mechanical check for an `api_key`-shaped
  settings field, not text-mined from the description (one skill's
  own description literally says "no API key", which a naive keyword
  match would have gotten backwards).

### Connectivity badge (Offline / Hybrid / Online)

Primarily read from the skill's own description - an explicit
"fully offline"/"no internet" claim is trusted as the author's own
authority on their skill. Falls back to checking PyPI's declared
dependencies against a small, curated list of known internet-fetching
libraries (`requests`, `bs4`, `feedparser`, ...) only when the
description doesn't address connectivity at all.

### Category grouping

Inferred from each entry's own tags (skill.json tags, or GitHub
topics for tier-3 entries) against a small canonical category list
(Education, Utility, Entertainment, Daily, Music, Games, ...) -
anything that doesn't match lands in "Other".

## Maintenance

Fully automated via `scripts/generate_klondike_data.py`, run weekly
by GitHub Actions (`.github/workflows/update-mercantile.yml`), plus
on-demand via `workflow_dispatch`. Add an `owner/repo` line to
`ignore.txt` to manually exclude a specific repo (a broken fork left
with a stale topic tag, an abandoned experiment, etc.) even if it
would otherwise match the discovery search.

## Related

- [andlo/ovos-skills-directory](https://github.com/andlo/ovos-skills-directory) -
  andlo's own curated, personal skill directory (higher bar: PyPI-published
  only, no tiers).
- [OpenVoiceOS/OVOS-skills-store](https://github.com/OpenVoiceOS/OVOS-skills-store) -
  the official, PR-reviewed OVOS Skill Store.
