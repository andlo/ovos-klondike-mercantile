# ⛏️ OVOS Klondike Mercantile

A global, automatically-discovered directory of **OVOS skills,
plugins, addons, and tools across all of GitHub** - not just one
author's work. If [andlo's own skills directory](https://github.com/andlo/ovos-skills-directory)
is a curated personal store, this is the mercantile at the edge of
town: everything that might be gold gets a place on the shelf,
clearly labeled by how sure we are it's the real thing.

**Live site**: [andlo.github.io/ovos-klondike-mercantile](https://andlo.github.io/ovos-klondike-mercantile/)

- [How this works](#how-this-works)
- [What's on the detail page](#whats-on-the-detail-page)
- [Site structure](#site-structure)
- [Maintenance](#maintenance)
- [Related](#related)

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
   GitHub - catches things that exist but weren't found by signal 1
   (missing skill.json, misplaced, or not written yet). Explicitly
   includes forks (`fork:true`) - GitHub excludes them by default,
   and several real, actively-maintained official OpenVoiceOS skills
   (`ovos-skill-alerts`, `ovos-skill-easter-eggs`, `ovos-skill-ip`,
   `ovos-skill-date-time`) are technically still registered as
   forks of their original Mycroft-AI predecessors, never detached.
   `TRUSTED_FORK_OWNERS` in the script then decides which forks are
   actually kept - known first-party OVOS-ecosystem orgs (OpenVoiceOS,
   NeonGeckoCom, OscillateLabsLLC, TigreGotico, JarbasHiveMind,
   smartgic), not random personal test-forks.

### Component types: not just Skills

`skill.json` is a **Skill**-specific manifest, but most of what this
ecosystem is made of isn't a skill - it's a plugin. Component type is
derived from OVOS's own authoritative signal for this: **namespaced
entry-point group names** declared in `setup.py`/`pyproject.toml`
(e.g. `opm.ocp.extractor`, `ovos.plugin.pipeline`), the same
mechanism `ovos-plugin-manager` itself uses at runtime. This catches
OCP media plugins, pipeline plugins, personas, solvers, TTS/STT/wake-
word/PHAL/G2P/VAD plugins, and more - each gets a readable label
(unrecognized entry-point groups still get one instead of being
dropped, e.g. `opm.some_new_thing` → "Some New Thing Plugin").

A repo with a real installable package (`setup.py`/`pyproject.toml`
declaring a `name=`) but no skill- or plugin-specific signal at all
is labeled a **Tool** - catches CLI clients and helper libraries that
were previously excluded outright.

Every entry's `type_group` (Skill / Plugin / Tool) drives the site's
grouping and the type filter's hierarchy (Skill and Tool are
standalone options; every specific plugin type nests under one
"Plugins" group).

### Tiers

Every entry is one of three tiers, based on whether a **formal
manifest** was found for its actual type - not specifically
`skill.json`, since most of this store isn't skills:

- **Looks Complete** (tier 1): has a confirmed manifest for its type
  (`skill.json` for Skills, or a declared entry-points group for
  Plugins), published on PyPI, has a GitHub release - **or** is
  already listed in the official [OVOS Skill Store](https://openvoiceos.github.io/OVOS-skills-store/),
  which is treated as an even stronger completeness signal (a real
  OVOS maintainer reviewed and approved it) since the official store
  doesn't require PyPI or a release either. Deliberately *not*
  called "Verified" - this checks that the expected pieces are
  present, not that the thing actually works.
- **Incomplete** (tier 2): has a confirmed manifest, but is missing
  a PyPI release and/or a GitHub release - shown with an explicit
  "Not on PyPI" / "No release" badge rather than excluded. The goal
  is to include as much as possible, not gatekeep on publishing
  status.
- **Inferred, Unconfirmed** (tier 3): **no** formal manifest found
  at all. Falls through two last-resort signals: skill-shaped
  `__init__.py` code (guessed as "Skill"), then a real installable
  package with no skill/plugin signal (guessed as "Tool"). A
  topic-tagged repo matching neither is excluded outright - the
  topic alone isn't proof of anything.

### Cross-referencing

Each entry is checked against:
- **PyPI** - latest version, release date, and dependencies (the
  latter feeds the offline/hybrid/online badge - see below).
- **The official OVOS Skill Store** - entries already listed there
  get an "OVOS Store" badge (and the tier-1 override above).
- **[OVOS Localize](https://openvoiceos.github.io/ovos-localize/)** -
  the official translation platform's own tracked-repo list. Entries
  it tracks get a right-aligned "Translate"/"Help Translate" link.
  Fetched via a plain HTTP GET (not the GitHub API), so this costs
  nothing against the rate limit regardless of how many entries are
  processed.
- **`settingsmeta.json`** - a mechanical check for an `api_key`-shaped
  settings field, not text-mined from the description (one skill's
  own description literally says "no API key", which a naive keyword
  match would have gotten backwards).

### Descriptions and setup notes, from the README when needed

If neither `skill.json` nor GitHub's own repo "About" field has a
description, the repo's own README is used as a fallback - common
specifically for PHAL plugins, which often have a real, substantial
README but an empty About field.

Separately, and for **every** entry regardless of whether a
description already exists, the README is also scanned for headings
matching install/setup/config/getting-started - repo-specific steps
beyond a generic `pip install X` (editing `mycroft.conf`, enabling a
systemd service, setting an API key, etc). A repo can have more than
one matching section; all are shown, unmodified, on the detail page.

### Connectivity badge (Works Offline / Offline + Online / Needs Internet)

Primarily read from the entry's own description - an explicit
"fully offline"/"no internet" claim is trusted as the author's own
authority. Falls back to checking PyPI's declared dependencies
against a small, curated list of known internet-fetching libraries
(`requests`, `bs4`, `feedparser`, ...) only when the description
doesn't address connectivity at all.

### Language flags

For **Skill** entries only (plugins/tools don't follow this
convention in practice), the `locale/` directory is listed to find
which languages are supported, shown as country flag emoji computed
directly from each locale code's region subtag via Unicode
"regional indicator symbol" math (`en-us` → 🇺🇸) - no lookup table
needed.

### Category grouping

Skills group by an inferred content category (Education, Utility,
Entertainment, Daily, Music, Games, ...), read from tags against a
small canonical list - anything unmatched lands in "Other".

### Stars, forks, and "new"

Stars/forks are already present in the repo data fetched for every
candidate - shown as a quality signal, sortable. `open_issues_count`
is fetched but deliberately **not** shown as a badge - a high count
is ambiguous (could mean "actively used, lots of feedback" or
"abandoned, nobody fixing bugs"), not a clean signal on its own; it's
still in the raw JSON for anyone who wants it.

"New" is two genuinely different things, shown as separate,
independently-capped sections: **New repos** (the repo itself is
young, from its GitHub creation date - a new addition to the
ecosystem) vs. **Recently updated** (an existing project shipped a
fresh release). A repo matching both only shows once, under "New
repos".

## What's on the detail page

Clicking any card opens `detail.html?id=<owner-repo>` with:
- The full, untruncated description and full tag/example lists
  (cards truncate both).
- **Install instructions**: `pip install <package>` if on PyPI, else
  a git-based fallback (`pip install git+<source>.git`) if it's only
  on GitHub.
- **Additional setup/configuration**, extracted from the README (see
  above) - explicitly labeled as extracted-as-is, not verified.
- An explicit **license warning** when none is declared (not just a
  small badge easy to miss) - explaining what "no license" legally
  means (default "all rights reserved") in plain language.
- Full repository stats: type, license, created date, last updated
  date, stars, forks, open issues, PyPI version.

## Site structure

Static, no build step - `docs/` is served directly by GitHub Pages:

- `docs/index.html` + `docs/app.js` - the main browsable/filterable/
  sortable store.
- `docs/detail.html` + `docs/detail.js` - the per-entry detail page.
- `docs/shared.js` - constants and pure rendering helpers (badges,
  generic per-type icons, date formatting, language flags, ...)
  used by both pages, loaded before either's own script.
- `docs/skills.json` - the raw data feed (also linked in the site
  footer).
- `docs/meta.json` - generation stats (repos reviewed, entries
  included, generated-at timestamp), shown in the page header.
- `skills/` - one JSON file per entry (same data as `skills.json`,
  split out for easier diffing/debugging), matching the pattern
  `OpenVoiceOS/OVOS-skills-store` uses for its own `raw_jsons/`.

## Maintenance

Split into two GitHub Actions workflows so a pure frontend change
doesn't force an expensive full re-run:

- **`update-mercantile.yml`** (~15-20 min): the actual discovery +
  cross-referencing script. Runs weekly (Mondays), on-demand via
  `workflow_dispatch`, and automatically whenever
  `scripts/generate_klondike_data.py` itself changes (the only file
  where a change could affect what gets fetched). Uses a
  `concurrency` group (queue, not cancel) so back-to-back
  script-changing pushes can't run two full passes at once and
  conflict when committing.
- **`deploy-static.yml`** (~1 min): redeploys whatever's already
  committed under `docs/` whenever `index.html`, `detail.html`,
  `app.js`, `detail.js`, `shared.js`, or `style.css` change - no
  GitHub/PyPI calls, no token needed.

Both use a minimal-scope fine-grained PAT (`PUBLIC_READ_TOKEN`,
"Public Repositories: read-only") for the parts that call the GitHub
API - deliberately not a broader personal token, since none of this
needs write access anywhere. (One real gotcha hit along the way:
some orgs, including OpenVoiceOS, reject fine-grained PATs whose
lifetime exceeds 366 days - the token needs a real expiration date
set, not "no expiration".)

Add an `owner/repo` line to `ignore.txt` to manually exclude a
specific repo (a broken fork left with a stale topic tag, an
abandoned experiment, etc.) even if it would otherwise match the
discovery search.

## Related

- [andlo/ovos-skills-directory](https://github.com/andlo/ovos-skills-directory) -
  andlo's own curated, personal skill directory (higher bar: PyPI-published
  only, no tiers).
- [OpenVoiceOS/OVOS-skills-store](https://github.com/OpenVoiceOS/OVOS-skills-store) -
  the official, PR-reviewed OVOS Skill Store.
- [OpenVoiceOS/ovos-localize](https://github.com/OpenVoiceOS/ovos-localize) -
  the official translation platform.
