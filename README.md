# ⛏️ OVOS Klondike Mercantile

A global, automatically-discovered directory of **OVOS skills,
plugins, addons, and tools across all of GitHub** - not just one
author's work. If [andlo's own skills directory](https://github.com/andlo/ovos-skills-directory)
is a curated personal store, this is the mercantile at the edge of
town: everything that might be gold gets a place on the shelf,
clearly labeled by how sure we are it's the real thing.

**Live site**: [andlo.github.io/ovos-klondike-mercantile](https://andlo.github.io/ovos-klondike-mercantile/)

**Maintaining an OVOS repo and want it listed or correctly classified?**
See [Getting your repo found and correctly listed](https://andlo.github.io/ovos-klondike-mercantile/for-maintainers.html)
for the actual, practical checklist - what follows below is the
deeper technical explanation for anyone curious how the discovery
itself works.

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
  already listed in OVOS's own [upcoming Skill Store](https://openvoiceos.github.io/OVOS-skills-store/)
  (not yet officially launched), which is treated as an even
  stronger completeness signal (a maintainer reviewed and merged it)
  since that store doesn't require PyPI or a release either.
  Deliberately *not* called "Verified" - this checks that the
  expected pieces are present, not that the thing actually works.
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
- **OVOS's own upcoming Skill Store** (not yet officially launched) -
  entries already listed there get an "OVOS Store" badge (and the
  tier-1 override above).
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

### Tested on OVOS

Every Looks Complete skill and pipeline plugin (not archived) is tested
against OVOS's release channels: **testing** (what the OVOS installer
installs by default), **alpha** (its other choice) and **stable** (not
offered by the installer today; kept for the next stable release)
(issue #6, phases 1-2):

- **Level 1, installs:** `pip install` under the channel's own
  `constraints-<channel>.txt` from OpenVoiceOS/OpenVoiceOS (the file the
  installer itself uses), fetched live.
  When the channel pins the package itself, that pinned version is tested.
- **Level 2, loads:** booted in MiniCroft with every language the
  installed version ships (one boot: the first language as `lang`, the
  rest as `secondary_langs`). What it registered is recorded by kind
  (intents per language, fallback, common query, OCP, other), so provider
  skills without intents pass.
- **Level 3, routes (skills, phase 2):** the skill's own golden
  utterances (`test/end2end/golden_utterances*.jsonl` at the git tag of the
  tested version) are sent through the OVOS installer's pipeline with the
  installer's default skills loaded (`scripts/compat/baseline.py`, read
  live from ovos-installer: today
  `ovos-core[skills-essential,skills-internet,skills-audio]` under the
  channel's constraints). Each row must reach the skill; a miss records who
  took it. One MiniCroft per language serves a whole shard
  (`scripts/compat/route.py`), so the default skills are booted once per
  shard and language, not once per skill. Level 3 is reached at 80% of the
  counted rows; the label shows the numbers (`✓ 14/14 golden`). Rows taken
  by another skill of the same shard are collisions, shown but not
  counted. Up to 4 languages per shard (en-US first), at most 30 minutes
  of routing per shard.
- **The Klondike test (level 3 on a well-equipped install, #13):** the
  same rows, routed with the **Klondike profile** loaded: the installer's
  default skills, its extra skills, and a curated list in
  `compat/klondike-profile.toml` (skills, and pipeline plugins placed
  relative to the installer's pipeline, e.g. the common-reading pipeline
  after stop-high). A curated entry is in the profile on a channel when it
  passes level 2 there. One job per channel boots the profile once (en-US)
  with every skill that passed level 2 loaded next to it: a sentence a
  profile skill takes counts, one another tested skill takes does not
  (two alternatives outside the profile are never tested against each
  other). The same run gives the profile against itself. It never changes
  the level or the channel badge. The profile is published per channel as
  `docs/compat/klondike-profile-<channel>.txt` (pip requirements) and
  `klondike-mycroft-<channel>.json` (the pipeline), and test reports from a
  device that runs it count as Klondike-test reports.
- **Generated utterances:** for skills without golden files,
  `scripts/compat/generated.py` calls `ovoscope generate`
  (OpenVoiceOS/ovoscope#224, pinned as `GENERATOR_SPEC` in the workflow)
  and keeps rows with `"source": "generated"`. They run and are counted
  separately from golden, and stay out of labels, badges and the sort
  (`PUBLIC_GENERATED` / `COMPAT_PUBLIC_GENERATED`) until #224 is merged or
  settled. An ovoscope without `generate` makes them "unavailable".

The channel stack comes from OpenVoiceOS/ovos-test-harness's own
`channel_compat` install (`test/channel_compat/install_channel.sh`,
pinned by SHA in the workflow), run unchanged, plus two things a device
has that the harness stack does not always include: the default
translate/lang-detect plugins, and a test driver (ovoscope) whose own
declared requirements accept the channel. On stable that is ovoscope
0.6.0, driven through the same boot helper.

A real device can be brought onto the same stack with ovos-tui-client's
`ovos-tui --set-channel <channel>` (0.3.0a2 or newer), run on the device after
the OVOS installer (in its OVOS venv, as the user that owns it);
`scripts/compat/device_setup.sh <channel>` does the same for a device without
ovos-tui-client, and is where it was prototyped. An installer
install is not always the channel: it resolves in separate batches, and
on alpha with pre-releases allowed for everything, so a device can end up
below the channel's floors, with third-party betas (httpx 1.0.dev6 broke
huggingface_hub and with it ovos-m2v-pipeline, OpenVoiceOS/ovos-installer#635)
and with plugins whose caps conflict with the core. The script does what
this store does: the channel's stack packages by name under the live
constraints (pip, no `--pre`), the `LOCKED_STACK` pinned, everything else
the channel names upgraded under constraints and lock, and pre-releases
outside the channel moved to final releases unless a dependent asks for
one. What cannot follow the channel is reported, never downgraded into
place. On a Mark II this gave the same versions as `klondike-stack-alpha.txt`.
The two must keep the same rules: `LOCKED_STACK` here, `setchannel.LOCKED_STACK`
there.

Results that are not the package's fault are never shown as a failure:
`error` (infrastructure trouble, retried next run), `unsupported`
(stable's ovos-core has no loader for third-party pipeline plugins) and
`needs_device` (loading blocks in the package's own code waiting for
device services; the file:line is recorded) and `needs_config` (the
package's own load error says it needs an API key, account or identity).
A skill that only fails with some of its languages configured is a pass
with those languages flagged, since a device only loads its own.

Shown as a label per channel on cards, followed by one quality label:
**🎯 Routes** (level 3: at least 80% of its own golden utterances reach
it) or **⛏ Klondike Gold** (and still at least 80% with the Klondike
profile loaded). The quality label comes from testing, the installer's
default; when testing has no result, from alpha, named in the label
("🎯 Routes · alpha"); never from stable. Also: a "Tested on OVOS" filter
(Routes / Klondike Gold; works / routes / fails per channel; works on
testing and alpha), the
default "Recommended" sort (testing ×10, stable ×3, alpha ×1:
fails 0, untested 1, loads 2, golden routing 3 plus the share routed; ties
by stars), a section on the detail page
(level, date, versions tested against, failure reason, log excerpt,
languages), and a README badge via a shields.io endpoint on Pages:
`https://img.shields.io/endpoint?url=https://andlo.github.io/ovos-klondike-mercantile/badges/<skill_id>/<channel>.json`.
The badge id is the id the skill registers under (from its entry point),
falling back to the entry id if two entries would share it.

## What's on the detail page

Clicking any card opens `detail.html?id=<owner-repo>`, ordered from "what
is it" down to "for the maintainer":

1. **Header**: name, author, version, language flags (the only place flags
   appear), badges, an archived notice if it applies, the full untruncated
   description, and GitHub / PyPI / Translate buttons.
2. **Install**: `pip install <package>` if on PyPI, else a git-based
   fallback. README setup notes and `settingsmeta.json` settings are
   folded away underneath, labelled as extracted as-is, not verified.
3. **Try saying**: the full example list (cards truncate it).
4. **Tested on OVOS**: one line per release channel (status, version
   tested, date) and at most one line saying what is wrong. Versions tested
   against, registrations, languages (by code) and the log excerpt are in a
   folded "Test details"; the log only shows when something failed.
5. **About this listing**: the completeness rating and its facts, the
   license (with a plain-language warning when none is declared), repo
   stats and tags, in one block.
6. **For the maintainer**: the README badge snippet (folded), Request test,
   Request update, the maintainer guide, Report a problem.

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

- **`update-mercantile.yml`**: the actual discovery + cross-
  referencing script. Runs every 3 hours, on-demand via
  `workflow_dispatch`, and automatically whenever
  `scripts/generate_klondike_data.py` itself changes (the only file
  where a change could affect what gets fetched). Processes new
  candidates and a bounded, rotating batch of already-known ones per
  run (see `BATCH_SIZE`/`NEW_BATCH_SIZE` in the script) rather than
  the whole list every time - a full sweep-everyone-every-run design
  kept hitting real rate-limit trouble once README/setup-section/
  locale-listing lookups were added per candidate. A `concurrency`
  group (queue, not cancel) plus a push-retry-with-rebase in the
  commit step handle back-to-back runs landing close together
  without losing work.
- **`deploy-static.yml`** (~1 min): redeploys whatever's already
  committed under `docs/` whenever `index.html`, `detail.html`,
  `app.js`, `detail.js`, `shared.js`, or `style.css` change - no
  GitHub/PyPI calls, no token needed.

- **`skill-compat.yml`**: the channel tests. Nightly, plus
  `workflow_dispatch` (`only`, `force`, `full`). Incremental: a package
  is re-tested only when its key changes (package, resolved version,
  channel, constraints hash, languages, harness SHA, `RUNNER_VERSION` in
  `scripts/compat/plan.py`). Three jobs split by trust: `plan`
  (read-only), `test` (installs arbitrary PyPI packages: no secrets, no
  token permissions, anonymous clones) and `publish` (write access;
  validates the artifacts as untrusted data and writes only
  `docs/compat/` and `docs/badges/`). The crawler owns `skills.json` and
  attaches the `compat` field from `docs/compat/results.json` on every
  run, so the two workflows never write the same file. The pages read
  `docs/compat/results.json` themselves too, so labels and the filter
  update as soon as a test run publishes, not only after the next crawl.
  `scripts/compat/local_run.sh` reproduces one shard locally in podman.
- **`process-test-request.yml`**: "Request test" on a detail page opens
  an issue titled `Test request: <entry id>`; this validates it and
  starts `skill-compat.yml` for that entry (at most once per entry per
  24h).

`update-mercantile.yml` uses a minimal-scope fine-grained PAT (`PUBLIC_READ_TOKEN`,
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
  OVOS's own upcoming, PR-reviewed Skill Store (not yet officially launched).
- [OpenVoiceOS/ovos-localize](https://github.com/OpenVoiceOS/ovos-localize) -
  the official translation platform.
