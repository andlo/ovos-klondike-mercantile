// Shared between index.html (app.js) and detail.html (detail.js) -
// constants and pure rendering helpers with no dependency on either
// page's specific DOM structure.

const STORE_BADGE_SVG = `<svg viewBox="0 0 20 20" fill="currentColor" aria-hidden="true">
  <path fill-rule="evenodd" d="M16.7 5.3a1 1 0 0 1 0 1.4l-7 7a1 1 0 0 1-1.4 0l-3.5-3.5a1 1 0 1 1 1.4-1.4l2.8 2.8 6.3-6.3a1 1 0 0 1 1.4 0z" clip-rule="evenodd"/>
</svg>`;

// Generic per-type placeholder icons (no external asset, data: URIs)
// shown when a skill/plugin/tool has no icon of its own, or its icon
// URL fails to load. One shape per type_group (Skill/Plugin/Tool)
// instead of a single identical icon for everything, so a card
// without its own icon still hints at what kind of thing it is.
function genericIconSvg(glyphPath) {
  return (
    "data:image/svg+xml;utf8," +
    encodeURIComponent(
      `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 44 44">
         <rect width="44" height="44" rx="10" fill="#e2e5ea"/>
         <path d="${glyphPath}" fill="#9aa0ab"/>
       </svg>`
    )
  );
}

const GENERIC_ICON_SKILL = genericIconSvg(
  "M22 11c-6.6 0-11 4-11 9s4.4 9 11 9c1 0 2-.1 2.9-.3l4.6 2.8-.7-4.4C30.8 25.4 33 22.5 33 20c0-5-4.4-9-11-9z"
);
const GENERIC_ICON_PLUGIN = genericIconSvg(
  "M15 13h6a2 2 0 012-2 2 2 0 012 2h6v6a2 2 0 012 2 2 2 0 01-2 2v6h-6a2 2 0 01-2 2 2 2 0 01-2-2h-6v-6a2 2 0 002-2 2 2 0 00-2-2v-6z"
);
const GENERIC_ICON_TOOL = genericIconSvg(
  "M27.7 13.3a5 5 0 00-6.6 6l-9.5 9.5 2.6 2.6 9.5-9.5a5 5 0 006-6.6l-3 3-2-2 3-3z"
);
const GENERIC_ICON_INFRA = genericIconSvg(
  "M13 14h18v5H13v-5zm0 8h18v5H13v-5zm0 8h18v5H13v-5z"
);
const GENERIC_ICON = GENERIC_ICON_PLUGIN; // ultimate fallback

// Extra class and style for an entry's icon <img>. Icons the crawler found
// itself (README header, repo tree) aren't always square, so they are
// contained, not cropped. A Mycroft-style README icon is a black glyph
// meant for a coloured tile (card_color): drawn white on that colour.
function iconExtras(skill) {
  const color = /^#[0-9a-fA-F]{3,8}$/.test(skill.icon_color || "") ? skill.icon_color : null;
  if (color) return { cls: " icon-tile", style: ` style="background:${color}"` };
  if (skill.icon && (skill.icon_source === "readme" || skill.icon_source === "repo")) return { cls: " icon-found", style: "" };
  return { cls: "", style: "" };
}

function genericIconFor(skill) {
  if (skill.type_group === "Skill") return GENERIC_ICON_SKILL;
  if (skill.type_group === "Tool") return GENERIC_ICON_TOOL;
  if (skill.type_group === "Infrastructure") return GENERIC_ICON_INFRA;
  return GENERIC_ICON_PLUGIN;
}

const MAX_DESCRIPTION_LENGTH = 160;

// Connectivity labels deliberately avoid the word "Offline" alone -
// on its own it reads as "the skill is unavailable" rather than
// "works without internet". "lan" is a distinct category from
// "offline": a LAN-only tool still uses networking (mDNS, local
// discovery, etc), just not the internet - a genuinely different
// thing than something that touches no network at all.
const CONNECTIVITY_META = {
  offline: { label: "Works Offline", cls: "badge-offline" },
  lan: { label: "LAN Only", cls: "badge-lan" },
  hybrid: { label: "Offline + Online", cls: "badge-hybrid" },
  online: { label: "Needs Internet (WAN)", cls: "badge-online" },
};

// These intentionally do NOT say "Verified" - this system checks
// that the expected PIECES are present, not that the skill actually
// works. Real verification would mean running `pip install` and
// importing it - a distinct, larger feature this labeling doesn't
// claim to already be.
const TIER_META = {
  1: { label: "Looks Complete", cls: "badge-verified" },
  2: { label: "Incomplete", cls: "badge-partial" },
  3: { label: "Inferred, Unconfirmed", cls: "badge-unverified" },
};

function escapeHtml(str) {
  const div = document.createElement("div");
  div.textContent = str ?? "";
  return div.innerHTML;
}

// Defense in depth: the generator normalizes tags/examples to always
// be arrays (see generate_klondike_data.py's normalize_tags, added
// after a real skill.json declared "tags" as a plain string, which
// crashed every .map() call on it). Kept here too in case a future
// data source has a shape this hasn't anticipated.
function asArray(value) {
  return Array.isArray(value) ? value : [];
}

function pipelineLabel(pipelinePackage) {
  const words = pipelinePackage
    .replace(/^ovos-/, "")
    .replace(/-plugin$/, "")
    .split("-")
    .map((w) => w.charAt(0).toUpperCase() + w.slice(1));
  // Don't append "Pipeline" again if the package name already
  // contains it as its own word (e.g. "common-reading-pipeline-
  // plugin") - found by inspection: this produced "Common Reading
  // Pipeline Pipeline" for that exact package before this check.
  if (words[words.length - 1] !== "Pipeline") words.push("Pipeline");
  return words.join(" ");
}

function truncate(text, maxLength) {
  if (!text || text.length <= maxLength) return text || "";
  return text.slice(0, maxLength).replace(/\s+\S*$/, "") + "…";
}

function renderBadges(skill) {
  const badges = [];

  if (skill.component_type && skill.component_type !== "Skill") {
    badges.push(`<span class="badge badge-type">${escapeHtml(skill.component_type)}</span>`);
  }
  if (skill.pipeline) {
    // Was extracted into the data (pipelineLabel() existed) but
    // never actually shown anywhere - found by inspection: a
    // common-reading-pipeline provider skill (component_type
    // "Skill") had no visible way to tell it apart from a regular
    // skill, unlike an OCP provider (which gets its own distinct
    // component_type via entry-points detection). Same visual
    // treatment as the type badge, since it's the same kind of "this
    // is part of a family" signal.
    badges.push(`<span class="badge badge-type">${escapeHtml(pipelineLabel(skill.pipeline))} Provider</span>`);
  }

  const tier = TIER_META[skill.tier];
  if (tier) badges.push(`<span class="badge ${tier.cls}">${tier.label}</span>`);

  if (skill.in_ovos_store) {
    badges.push(`<span class="badge badge-store">${STORE_BADGE_SVG} OVOS Store</span>`);
  }
  const conn = CONNECTIVITY_META[skill.connectivity];
  if (conn) badges.push(`<span class="badge ${conn.cls}">${conn.label}</span>`);
  if (skill.requires_api_key) {
    badges.push(`<span class="badge badge-key">API key</span>`);
  }
  if (skill.component_type !== "Infrastructure") {
    // "Not on PyPI"/"No release" imply a gap in something that was
    // supposed to be installable - doesn't apply to Infrastructure
    // (docs, the store's own data repo, installers, this site's own
    // repo, etc), which was never meant to be pip-installed at all.
    // License/archived stay - those genuinely apply to any repo.
    if (!skill.on_pypi) {
      badges.push(`<span class="badge badge-warn">Not on PyPI</span>`);
    }
    if (!skill.has_release) {
      badges.push(`<span class="badge badge-warn">No release</span>`);
    }
  }
  if (!skill.license) {
    badges.push(`<span class="badge badge-warn">No license</span>`);
  }
  if (skill.archived) {
    badges.push(installerChannels(skill).length
      ? `<span class="badge badge-warn" title="${escapeHtml(installerNote(skill))}">Archived · still installed by OVOS</span>`
      : `<span class="badge badge-warn">Archived</span>`);
  }
  return badges.join("");
}

// Channel test results (compat field from the crawler, built from
// docs/compat/results.json by the Channel compat tests workflow). One small
// label per tested channel; untested channels show nothing.
const COMPAT_CHANNELS = ["stable", "testing", "alpha"];
const COMPAT_LEVEL_TEXT = {
  0: "level 0: does not install under the channel's constraints",
  1: "level 1: installs, but does not load in MiniCroft",
  2: "level 2: installs and loads in MiniCroft",
  3: "level 3: its golden utterances reach it with the OVOS installer's default skills loaded",
};

// Same switch as PUBLIC_GENERATED in scripts/compat/feed.py: generated
// utterances (ovoscope generate, OpenVoiceOS/ovoscope#224) are tested but
// not shown until #224 is merged or settled upstream.
const COMPAT_PUBLIC_GENERATED = false;
// Same as LEVEL3_RATIO in scripts/compat/feed.py.
const COMPAT_LEVEL3_RATIO = 0.8;

// Same as STOP_RESULTS in scripts/compat/publish.py; only these three mean
// something on a card ("nothing_to_stop": it was done before "stop").
function stopResult(rec) {
  const r = ((rec && rec.routing) || {}).stop || {};
  return ["stops", "keeps_going", "stuck"].includes(r.result) ? r.result : null;
}

function routingCounts(rec, run, field = "routing") {
  const r = ((rec && rec[field]) || {})[run] || {};
  if (r.status !== "ok" || !r.counted) return null;
  return { hit: r.hit || 0, counted: r.counted };
}

// Same rules as scripts/compat/feed.py label(): one short label and a
// state (pass / warn / fail / unsupported / untested) per channel result.
// Pages read docs/compat/results.json directly, so a finished test run
// shows at once instead of waiting for the next crawl to copy it into
// skills.json (the crawler's compat field is the fallback).
const COMPAT_GREY = { unsupported: "not supported", needs_device: "needs device", needs_config: "needs config" };

function compatFromRecord(rec) {
  let label = "untested";
  let state = "untested";
  if (rec && COMPAT_GREY[rec.status]) {
    label = COMPAT_GREY[rec.status];
    state = "unsupported";
  } else if (rec && rec.status === "fail") {
    label = (rec.level || 0) === 0 ? "✗ doesn't install" : "✗ doesn't load";
    state = "fail";
  } else if (rec && rec.status === "pass") {
    const booted = asArray(rec.languages_booted);
    const missing = asArray(rec.languages_missing);
    label = "✓ loads";
    state = asArray(rec.warnings).length ? "warn" : "pass";
    if (missing.length && booted.length) {
      label = `✓ loads · ${booted.length - missing.length}/${booted.length} langs`;
      state = "warn";
    }
    const golden = routingCounts(rec, "golden");
    if (golden) {
      if (golden.hit / golden.counted < COMPAT_LEVEL3_RATIO) {
        label = `✓ loads · ${golden.hit}/${golden.counted} golden`;
        state = "warn";
      } else {
        label = `✓ ${golden.hit}/${golden.counted} golden`;
        state = golden.hit === golden.counted && !missing.length && !asArray(rec.warnings).length ? "pass" : "warn";
      }
    }
    // The stop check (#16), shown only when there was something to stop.
    const stop = stopResult(rec);
    if (stop === "stops") label += " · stops";
    else if (stop === "keeps_going" || stop === "stuck") {
      label += " · doesn't stop";
      state = "warn";
    }
  }
  const out = { label, state, level: (rec && rec.level) || 0 };
  if (stopResult(rec)) out.stop = stopResult(rec);
  for (const k of ["version_tested", "tested_at", "channel_pinned"]) {
    if (rec && rec[k] !== undefined && rec[k] !== null) out[k] = rec[k];
  }
  for (const run of COMPAT_PUBLIC_GENERATED ? ["golden", "generated"] : ["golden"]) {
    const c = routingCounts(rec, run);
    if (c) out[run] = c;
  }
  return out;
}

// "Recommended" sort (issue #6). Per channel a skill scores:
//   0    fails (doesn't install / doesn't load)
//   1    Looks Complete but untested, or not testable here (grey)
//   2    loads (level 2); + up to 0.5 for generated utterances once shown
//   3-4  golden utterances measured: 3 + the share that reach the skill
// Channels are weighted by who runs them: testing ×10 (what the OVOS
// installer installs by default), stable ×3 (not offered by the installer
// today, but the slow, safe track a new stable release lands on), alpha ×1.
// So passing on testing ranks above untested and failing on testing below it. Not Looks Complete: tier 2 is -1,
// tier 3 -2. Ties go to stars.
// Reports from people (#6 maintainer, #9 community) fit inside the bands
// above, never across them:
//   a current maintainer pass on a channel we cannot test (untested/grey)
//   lifts it from 1 to 1.5 (1.7 at level 3): above untested, below our own
//   "loads"; community confirmations move a skill up or down by at most
//   0.45 within its band, with diminishing returns (communityWeight, same
//   formula as scripts/reports/feed.py).
function communityWeight(works, doesntWork) {
  const w = 0.3 * Math.log10(1 + (works || 0)) - 0.3 * Math.log10(1 + (doesntWork || 0));
  return Math.max(-0.45, Math.min(0.45, w));
}

function channelScore(c, r) {
  let score;
  if (!c || c.state === "untested" || c.state === "unsupported") score = 1;
  else if (c.state === "fail") score = 0;
  else if (c.golden) score = 3 + c.golden.hit / c.golden.counted - (["keeps_going", "stuck"].includes(c.stop) ? 0.3 : 0);
  else if (COMPAT_PUBLIC_GENERATED && c.generated) score = 2 + 0.5 * (c.generated.hit / c.generated.counted);
  else score = 2;
  if (!r) return score;
  if (score === 1 && r.maintainer === "pass") score = r.maintainer_level === 3 ? 1.7 : 1.5;
  return score + communityWeight(r.works, r.doesnt_work);
}

function recommendedRank(skill) {
  const channels = (skill.compat && skill.compat.channels) || null;
  const reports = skill.reports || {};
  if (!channels && skill.tier !== 1) return skill.tier === 2 ? -1 : -2;
  if (!channels) return 14;
  return channelScore(channels.testing, reports.testing) * 10 + channelScore(channels.stable, reports.stable) * 3
    + channelScore(channels.alpha, reports.alpha);
}

// docs/reports/index.json, read directly (like compat/results.json) so a
// stored report shows without waiting for the next crawl.
function compactReports(summary) {
  const out = {};
  for (const [ch, row] of Object.entries(summary || {})) {
    const m = row.maintainer, c = row.community || {};
    let state = null;
    if (m && m.status === "current") state = m.passes ? "pass" : "fail";
    else if (m) state = m.status;
    out[ch] = { maintainer: state, maintainer_level: m ? m.level : null,
      works: c.works || 0, partly: c.partly || 0, doesnt_work: c.doesnt_work || 0 };
  }
  return out;
}

function applyReports(skills, index) {
  const entries = (index && index.entries) || {};
  for (const skill of skills) {
    if (entries[skill.id]) skill.reports = compactReports(entries[skill.id]);
  }
  return skills;
}

function loadReportsIndex(cacheBust) {
  return fetch(`reports/index.json${cacheBust}`, { cache: "no-store" })
    .then((res) => (res.ok ? res.json() : null))
    .catch(() => null);
}

// Channels on which the OVOS installer installs this entry (#54), from
// compat/results.json "installer", as the last test run read it.
function installerChannels(skill) {
  return asArray(skill.installer_channels);
}

function installerNote(skill) {
  const chans = installerChannels(skill);
  const extra = skill.installer_profile === "extra" ? " with extra skills on" : "";
  return chans.length ? `The OVOS installer still installs it${extra} (${chans.join(", ")}), so it is tested like any other entry.` : "";
}

// Level 3 for a pipeline plugin (#52), from the channel's Klondike job:
// the sentences it took and handed to the skill they belong to (reaches)
// and the ones it took from that skill (takes). measured is false where
// the channel's ovos-core does not say which plugin matched a sentence;
// inProfile when the Klondike profile adds its stage (Gold is only given
// to those: the installer's own stages are what everything is measured on).
function pipelineRoute(doc, ch, pluginIds) {
  const k = ((doc && doc.klondike) || {})[ch] || {};
  const job = k.job || {};
  // A job from before #52 has no "pipelines": nothing to say yet.
  if (!job.run_at || !("pipelines" in job)) return null;
  const ids = asArray(pluginIds);
  const found = ids.map((i) => (job.pipelines || {})[i]).filter(Boolean);
  const added = asArray((k.profile || {}).added_stages).map((s) => s.replace(/-(high|medium|low)$/, ""));
  return {
    measured: job.attribution === true, channel: ch,
    reaches: found.reduce((n, f) => n + (f.reaches || 0), 0),
    takes: found.reduce((n, f) => n + (f.takes || 0), 0),
    examples: found.flatMap((f) => asArray(f.examples)).slice(0, 5),
    inProfile: ids.some((i) => added.includes(i)),
  };
}

function pipelineGold(c) {
  const p = c && c.pipeline_route;
  return !!(p && p.measured && p.inProfile && p.reaches > 0 && p.takes === 0 && ["pass", "warn"].includes(c.state));
}

function applyCompatResults(skills, doc) {
  const results = (doc && doc.results) || {};
  const installer = (doc && doc.installer) || {};
  for (const skill of skills) {
    const chans = COMPAT_CHANNELS.filter((ch) => (installer[ch] || {})[skill.id]);
    if (chans.length) {
      skill.installer_channels = chans;
      skill.installer_profile = installer[chans[0]][skill.id].profile;
    }
    const perChannel = results[skill.id];
    if (!perChannel) continue;
    const channels = {};
    for (const ch of COMPAT_CHANNELS) {
      if (perChannel[ch]) channels[ch] = compatFromRecord(perChannel[ch]);
      if (perChannel[ch] && perChannel[ch].kind === "pipeline") {
        const pr = pipelineRoute(doc, ch, perChannel[ch].plugin_ids);
        if (pr) channels[ch].pipeline_route = pr;
      }
      // Level 3 against the Klondike profile (#13), from the channel's
      // Klondike job: a line of its own, never part of the level or badge.
      const kres = ((((doc.klondike || {})[ch] || {}).job || {}).results || {})[skill.id];
      const k = kres && routingCounts(kres, "golden");
      if (k && channels[ch]) channels[ch].klondike = k;
    }
    skill.compat = { ...(skill.compat || {}), channels };
  }
  return skills;
}

function loadCompatResults(cacheBust) {
  return fetch(`compat/results.json${cacheBust}`, { cache: "no-store" })
    .then((res) => (res.ok ? res.json() : null))
    .catch(() => null);
}

// Filter helper for the store: does this skill match "loads:stable",
// "fails:alpha", "loads:both" or "tested"?
function matchesCompatFilter(skill, value) {
  if (!value) return true;
  const channels = (skill.compat && skill.compat.channels) || {};
  const loads = (ch) => channels[ch] && ["pass", "warn"].includes(channels[ch].state);
  const fails = (ch) => channels[ch] && channels[ch].state === "fail";
  if (value === "tested") return Object.values(channels).some((c) => c.state !== "untested");
  const routes = (ch) => channels[ch] && (channels[ch].level || 0) >= 3;
  const klondike = (ch) => channels[ch] && channels[ch].klondike
    && channels[ch].klondike.hit / channels[ch].klondike.counted >= COMPAT_LEVEL3_RATIO;
  // The two channels the OVOS installer offers.
  if (value === "loads:installer" || value === "loads:both") return loads("testing") && loads("alpha");
  const [kind, ch] = value.split(":");
  if (kind === "routes") return routes(ch);
  if (kind === "klondike") return klondike(ch);
  if (kind === "quality") {
    const q = qualityLabel(skill);
    return !!q && (ch === "routes" || q.kind === "klondike");
  }
  return kind === "loads" ? loads(ch) : kind === "fails" ? fails(ch) : true;
}

function compatTooltip(channel, c) {
  const parts = [`${channel}: ${c.label}`, COMPAT_LEVEL_TEXT[c.level] || ""];
  if (c.state === "unsupported") parts.push("not testable here: see the detail page");
  if (c.version_tested) parts.push(`tested v${c.version_tested}${c.channel_pinned ? " (the version this channel pins)" : ""}`);
  if (c.tested_at) parts.push(`on ${formatDate(c.tested_at)}`);
  return parts.filter(Boolean).join(" · ");
}

// One quality label per card: whether the skill's own golden utterances
// reach it (level 3), and whether they still do with the Klondike profile
// loaded (#13). From testing, the installer's default; when testing has no
// result, from alpha, named in the label since alpha changes all the time.
// Never from stable (legacy, no longer offered by the installer).
const QUALITY_CHANNELS = ["testing", "alpha"];

function qualityLabel(skill) {
  const channels = (skill.compat && skill.compat.channels) || {};
  // A pipeline plugin of the Klondike profile (#52): Gold when it reaches
  // skills and takes from none, where that is measured.
  for (const ch of QUALITY_CHANNELS) {
    if (pipelineGold(channels[ch])) {
      return { kind: "klondike", channel: ch, pipeline: channels[ch].pipeline_route };
    }
  }
  for (const ch of QUALITY_CHANNELS) {
    const c = channels[ch];
    if (!c || (c.level || 0) < 3 || !c.golden) continue;
    const k = c.klondike;
    const proof = !!(k && k.counted && k.hit / k.counted >= COMPAT_LEVEL3_RATIO);
    return { kind: proof ? "klondike" : "routes", channel: ch, golden: c.golden, klondike: k || null };
  }
  return null;
}

// The same label on the detail page, next to the routing result that
// earned it on this channel, so a card's label can be traced to it.
function qualityChip(kind, tip) {
  const text = kind === "klondike" ? "⛏ Klondike Gold" : "🎯 Routes";
  return ` <span class="compat-label quality-label quality-${kind}" title="${escapeHtml(tip)}">${text}</span>`;
}

function renderQualityLabel(skill) {
  const q = qualityLabel(skill);
  if (!q) return "";
  const text = (q.kind === "klondike" ? "⛏ Klondike Gold" : "🎯 Routes") + (q.channel === "testing" ? "" : ` · ${q.channel}`);
  const tip = q.pipeline ? [`In the Klondike test on ${q.channel}: took ${q.pipeline.reaches} sentences for the skills they belong to, and none from another skill`,
    q.channel === "alpha" ? "measured on alpha: testing's ovos-core does not say which pipeline plugin matched" : ""].filter(Boolean).join(" · ")
    : [`${q.golden.hit}/${q.golden.counted} of its golden utterances reach it on ${q.channel}`,
    q.klondike ? `${q.klondike.hit}/${q.klondike.counted} with the Klondike profile loaded` : "",
    q.channel === "alpha" ? "alpha changes all the time; testing has no result yet" : ""].filter(Boolean).join(" · ");
  return `<span class="compat-label quality-label quality-${q.kind}" title="${escapeHtml(tip)}">${escapeHtml(text)}</span>`;
}

function renderCompatLabels(skill) {
  const channels = (skill.compat && skill.compat.channels) || {};
  const reports = skill.reports || {};
  return COMPAT_CHANNELS
    .filter((ch) => (channels[ch] && channels[ch].state !== "untested") || reportLabelNeeded(channels[ch], reports[ch]))
    .map((ch) => {
      const c = channels[ch] || { state: "untested", label: "not tested here yet", level: null };
      const r = reports[ch] || {};
      const users = r.works ? ` · ${r.works} ${r.works === 1 ? "user" : "users"}` : "";
      // Our own result is shown as it is; a maintainer pass stands in only
      // where we could not test, in its own colour so the two never mix.
      if ((c.state === "untested" || c.state === "unsupported") && r.maintainer === "pass") {
        const tip = `${ch}: tested by the maintainer on their own device (level ${r.maintainer_level}); not testable here`;
        return `<span class="compat-label compat-maintainer" title="${escapeHtml(tip)}">✓ ${escapeHtml(ch)} · maintainer${escapeHtml(users)}</span>`;
      }
      const mark = { fail: "✗", unsupported: "–", untested: "·" }[c.state] || "✓";
      const tip = compatTooltip(ch, c) + (users ? ` · confirmed by${users.replace(" ·", "")}` : "");
      return `<span class="compat-label compat-${escapeHtml(c.state)}" title="${escapeHtml(tip)}">${mark} ${escapeHtml(ch)}${escapeHtml(users)}</span>`;
    }).join("");
}

function reportLabelNeeded(c, r) {
  return !!r && (r.maintainer === "pass" || r.works > 0);
}

function formatDate(iso) {
  if (!iso) return null;
  return new Date(iso).toLocaleDateString(undefined, {
    year: "numeric", month: "long", day: "numeric",
  });
}

// "unreleased" only makes sense as a claim for something that's
// EXPECTED to be on PyPI (a Skill/Plugin/Tool) - showing it for an
// Infrastructure entry (the official Skill Store's own data repo,
// an installer, this site itself, etc) is actively wrong: found by
// inspection, this site's own repo has real GitHub releases but
// showed "unreleased" simply because it has no PyPI package, which
// PyPI versioning was never meant to apply to in the first place.
// Returns null (render nothing) rather than a misleading label.
function versionLabel(skill) {
  if (skill.pypi_version) return `v${skill.pypi_version}`;
  if (skill.component_type === "Infrastructure") return null;
  return "unreleased";
}

// Bundled flag SVGs (docs/flags/, from flag-icons, MIT - see flags/LICENSE):
// emoji flags don't exist on Windows, where they show as two letters
// ("DK"), so cards and menus use images instead (issue #14). es.svg is the
// plain civil flag: the full one with its coat of arms is 90 KB.
// "eu" is deliberately NOT here: in a locale code it is never the European
// Union, and "eu-eu" (Basque) must not get the EU flag.
const FLAG_REGIONS = new Set(["ao", "ar", "at", "au", "az", "be", "bg", "br", "ca", "ch", "cn", "co", "cz", "de", "dk", "dz", "ee", "es", "fi", "fr", "gb", "gr", "hr", "hu", "id", "il", "in", "ir", "is", "it", "jp", "ke", "kr", "lt", "lv", "mx", "my", "mz", "nl", "no", "nz", "pl", "pt", "ro", "ru", "sa", "se", "sg", "si", "sk", "th", "tr", "tw", "ua", "us", "vn"]);

// Locale codes as repos actually name their locale/ folders are not always
// the usual language-REGION form: some are bare ("da"), some use a region
// that isn't a country ("eu-eu", "ar-xx"). skills.json keeps them exactly
// as found - the channel tests start each language by its real folder name -
// but the store shows and filters them under the usual code, so a skill with
// "da" sits under da-dk with everyone else. Codes not listed here, and that
// aren't standard, are shown as they are (see isStandardLocale).
const LOCALE_ALIASES = {
  "an": "an-es",
  "ar-xa": "ar-sa",
  "ar-xx": "ar-sa",
  "ca": "ca-es",
  "da": "da-dk",
  "de": "de-de",
  "es": "es-es",
  "eu": "eu-es",
  "eu-eu": "eu-es",
  "fr": "fr-fr",
  "gl": "gl-es",
  "it": "it-it",
  "kab": "kab-dz",
  "nl": "nl-nl",
  "pt": "pt-pt",
};

function normalizeLocale(code) {
  const lower = String(code || "").toLowerCase();
  return LOCALE_ALIASES[lower] || lower;
}

// Regions that are valid-looking two-letter codes but no country:
// private-use/pseudo-locale codes, and "eu".
const NON_COUNTRY_REGIONS = new Set(["eu", "un", "xa", "xb", "xx", "zz"]);

let regionNamesEn = null;
try { regionNamesEn = new Intl.DisplayNames(["en"], { type: "region" }); } catch { /* old browser */ }

// true for the usual language-REGION form with a real country as region.
// Unknown regions ("lm") are the ones Intl can't name - it hands the code
// back - so no list of every country has to live here.
function isStandardLocale(code) {
  const parts = String(code || "").toLowerCase().split("-");
  if (parts.length !== 2 || !/^[a-z]{2,3}$/.test(parts[0]) || !/^[a-z]{2}$/.test(parts[1])) return false;
  const region = parts[1];
  if (NON_COUNTRY_REGIONS.has(region)) return false;
  if (!regionNamesEn) return true;
  try { return regionNamesEn.of(region.toUpperCase()) !== region.toUpperCase(); } catch { return false; }
}

let languageNamesEn = null;
try { languageNamesEn = new Intl.DisplayNames(["en"], { type: "language" }); } catch { /* old browser */ }

// "da-dk" -> "Danish (Denmark)", "kab" -> "Kabyle"; the code itself if the
// browser can't name it.
function languageName(code) {
  if (!languageNamesEn) return String(code || "");
  try { return languageNamesEn.of(code) || String(code); } catch { return String(code || ""); }
}

// Rewrites each skill's languages (and its locale_content keys) to the
// usual codes, in place, keeping the repo's own folder names in
// languages_raw. Duplicates collapse ("kab" + "kab-dz" -> one kab-dz).
// Call once, right after skills.json is loaded.
function normalizeSkillLanguages(skills) {
  for (const skill of asArray(skills)) {
    const raw = asArray(skill.languages);
    skill.languages_raw = raw;
    skill.languages = [...new Set(raw.map(normalizeLocale))];
    if (skill.locale_content) {
      const content = {};
      for (const [code, value] of Object.entries(skill.locale_content)) {
        const key = normalizeLocale(code);
        // a folder already named the usual way wins over an alias of it
        if (!(key in content) || key === code.toLowerCase()) content[key] = value;
      }
      skill.locale_content = content;
    }
  }
  return skills;
}

function hasLanguageFlag(localeCode) {
  const parts = String(localeCode || "").split("-");
  const region = parts.length > 1 ? parts[parts.length - 1].toLowerCase() : null;
  return !!region && FLAG_REGIONS.has(region);
}

// "en-us" -> the flag for "us"; "da-dk" -> the flag for "dk", as an <img>.
// A bare language code ("en"), or a region without a bundled flag, falls
// back to the code itself, since there's no single flag for a language.
function languageFlag(localeCode) {
  if (!hasLanguageFlag(localeCode)) return escapeHtml(localeCode);
  const parts = String(localeCode).split("-");
  const region = parts[parts.length - 1].toLowerCase();
  return `<img class="flag" src="flags/${region}.svg" alt="${escapeHtml(region.toUpperCase())}" width="20" height="15" loading="lazy">`;
}

// Flag and code for a menu: the code once when there's no flag, so a code
// without one never reads "da da".
function languageLabel(localeCode) {
  const code = escapeHtml(localeCode);
  const inner = hasLanguageFlag(localeCode) ? `${languageFlag(localeCode)} ${code}` : code;
  return `<span title="${escapeHtml(languageName(localeCode))}">${inner}</span>`;
}

function renderLanguageFlags(skill, currentLang) {
  const languages = asArray(skill.languages);
  if (languages.length === 0) return "";
  const flags = languages.map((l) => {
    const isCurrent = !!currentLang && l === currentLang;
    const tip = `${languageName(l)} · ${l}`;
    return `<span class="lang-flag${isCurrent ? " lang-flag-current" : ""}" title="${escapeHtml(tip)}">${languageFlag(l)}</span>`;
  }).join("");
  return `<div class="lang-flags">${flags}</div>`;
}

// Detail page: the repo's own folder names that the store shows under
// another code, or that aren't the usual language-REGION form, so the
// maintainer can see what could be renamed. Empty when all is standard.
function renderLocaleCodeNote(skill) {
  const raw = asArray(skill.languages_raw);
  const notes = [];
  for (const code of raw) {
    const lower = String(code).toLowerCase();
    const shown = normalizeLocale(lower);
    if (shown !== lower) {
      notes.push(`<code>${escapeHtml(code)}</code> (shown as ${escapeHtml(shown)})`);
    } else if (!isStandardLocale(lower)) {
      notes.push(`<code>${escapeHtml(code)}</code>`);
    }
  }
  if (notes.length === 0) return "";
  return `<p class="setup-note locale-code-note">Non-standard locale folder name${notes.length > 1 ? "s" : ""} in the repo: ${notes.join(", ")}. The OVOS convention is language-REGION, e.g. da-DK.</p>`;
}

// Site-wide DISPLAY language - distinct from the existing
// "language-filter" dropdown (which controls WHICH skills show up
// at all, based on what they themselves support). This instead
// changes what TEXT is shown for skills that have a translated
// locale/<lang>/skill.json (see generate_klondike_data.py's
// fetch_locale_content) - name/description/examples - while every
// skill still stays visible regardless of the chosen language,
// falling back to the English base text when a given skill has no
// translation for it.
const SITE_LANGUAGES = [
  { code: "en-us", label: "English" },
  { code: "da-dk", label: "Dansk" },
  { code: "de-de", label: "Deutsch" },
  { code: "fr-fr", label: "Français" },
  { code: "es-es", label: "Español" },
  { code: "pt-pt", label: "Português" },
  { code: "it-it", label: "Italiano" },
  { code: "nl-nl", label: "Nederlands" },
];

const SITE_LANG_STORAGE_KEY = "klondike_site_lang";

function getSiteLanguage() {
  try {
    return localStorage.getItem(SITE_LANG_STORAGE_KEY) || "en-us";
  } catch {
    // localStorage can throw in some private-browsing modes -
    // English is always a safe, always-available fallback.
    return "en-us";
  }
}

function setSiteLanguage(code) {
  try {
    localStorage.setItem(SITE_LANG_STORAGE_KEY, code);
  } catch {
    // Same as above - the switcher still works for this page load,
    // it just won't be remembered on the next visit.
  }
}

// Returns {name, description, examples, translated} for a skill
// shown in the given display language. "translated" is true only
// when a real override was found (not just when the language
// happens to equal "en-us") - callers can use it to show a subtle
// "not translated yet" hint instead of silently mixing languages
// with no indication anything fell back.
function localizeSkill(skill, lang) {
  const override = (skill.locale_content && skill.locale_content[lang]) || null;
  return {
    name: (override && override.name) || skill.name,
    description: (override && override.description) || skill.description,
    examples: (override && override.examples) || skill.examples,
    translated: !!override,
  };
}

function populateSiteLangSelect(selectEl) {
  if (!selectEl) return;
  for (const { code, label } of SITE_LANGUAGES) {
    const opt = document.createElement("option");
    opt.value = code;
    // <option> can't hold an image, and emoji flags show as "DK" on Windows
    opt.textContent = label;
    selectEl.appendChild(opt);
  }
  selectEl.value = getSiteLanguage();
}
