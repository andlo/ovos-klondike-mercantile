// Detail page (detail.html) - reads ?id= from the URL, fetches the
// same skills.json the index page uses, and renders one entry in
// full: complete (untruncated) description, install instructions,
// a license warning when missing, and full repo stats (created,
// last updated, stars/forks/open issues).

const detailRoot = document.getElementById("detail-root");
const siteLangSelect = document.getElementById("site-lang");
let currentSiteLang = getSiteLanguage();
let currentSkill = null;

// Prefer real browser back-navigation over a fixed link to
// index.html - the browser's own history (via bfcache) restores the
// previous page exactly as left, including selected filter dropdown
// values, search text, and scroll position, none of which a plain
// href="index.html" link would preserve. Falls back to the normal
// link (browser default) when there's no history to go back to,
// e.g. this page was opened directly rather than navigated to from
// the store.
const backLink = document.getElementById("back-link");
backLink.addEventListener("click", (e) => {
  if (window.history.length > 1) {
    e.preventDefault();
    window.history.back();
  }
});

// A pip command only for what pip can install: package_name is set by the
// crawler only when the repo has a setup.py or pyproject.toml. Without one
// (docs, Docker/Ansible setups, add-ons, old-style skills) "pip install
// git+…" would just fail, so the page says so and points to the README.
function installInstructions(skill) {
  if (skill.on_pypi && skill.package_name) {
    return {
      label: "Install from PyPI",
      command: `pip install ${skill.package_name}`,
    };
  }
  if (skill.package_name && skill.source) {
    return {
      label: "Install from GitHub (not on PyPI)",
      command: `pip install git+${skill.source}.git`,
    };
  }
  return null;
}

function notPipInstallable(skill) {
  if (skill.package_name || !skill.source) return "";
  const readme = `${skill.source}#readme`;
  return `<p class="setup-note">Not a Python package (no <code>setup.py</code> or <code>pyproject.toml</code>), so it isn't installed with pip. See the <a href="${escapeHtml(readme)}" target="_blank" rel="noopener">README</a> for how to use it.</p>`;
}

function renderLicenseWarning(skill) {
  if (skill.license) return "";
  return `
    <div class="license-warning">
      ⚠️ <strong>No license declared.</strong> Without a license file,
      copyright law defaults to "all rights reserved" - the author
      hasn't granted permission to use, modify, or redistribute this
      code, even though it's publicly visible on GitHub. Check with
      the author before relying on it for anything beyond reading
      the source.
    </div>
  `;
}

function renderArchivedWarning(skill) {
  if (!skill.archived) return "";
  return `
    <div class="archived-notice">
      📦 <strong>This repo is archived on GitHub.</strong> The owner
      has marked it read-only, meaning no further updates, fixes, or
      issue responses are expected. Everything shown here reflects
      its last state before archiving - it may still work exactly as
      described, just isn't being maintained.
    </div>
  `;
}

function renderStatRow(label, value) {
  if (value === null || value === undefined || value === "") return "";
  return `<div class="stat-row"><span class="stat-label">${escapeHtml(label)}</span><span class="stat-value">${value}</span></div>`;
}

const REPO_URL = "https://github.com/andlo/ovos-klondike-mercantile";

const PAGES_URL = "https://andlo.github.io/ovos-klondike-mercantile";

let compatDoc = null; // docs/compat/results.json, loaded beside skills.json

function testRequestUrl(skill) {
  // Title-keyed (process-test-request.yml): labels in a new-issue link are
  // dropped for anyone without triage rights, so they can't be the trigger.
  const title = `Test request: ${skill.id}`;
  const body =
    `Please test this entry against the OVOS release channels now, rather than waiting for the nightly run.\n\n` +
    `- **Listing**: ${window.location.href}\n\n` +
    `<!-- Leave the title as it is: it's read automatically. -->\n`;
  return `${REPO_URL}/issues/new?${new URLSearchParams({ title, body }).toString()}`;
}

function updateRequestUrl(skill) {
  const title = `Update request: ${skill.name} (${skill.id})`;
  const body =
    `Please re-check this listing sooner than its normal rotation turn:\n\n` +
    `- **Repo**: ${skill.source}\n` +
    `- **Listing**: ${window.location.href}\n\n` +
    `**What changed / why re-check?**\n<!-- e.g. added a GitHub topic, ` +
    `set package_name in skill.json, published a release, archived the repo, etc -->\n`;
  const params = new URLSearchParams({ title, body, labels: "update-request" });
  return `${REPO_URL}/issues/new?${params.toString()}`;
}

function flagUrl(skill) {
  const title = `Flag: ${skill.name} (${skill.id})`;
  const body =
    `Please review this listing:\n\n` +
    `- **Repo**: ${skill.source}\n` +
    `- **Listing**: ${window.location.href}\n\n` +
    `**Reason** (illegal, dangerous, spam, abandoned, shouldn't be here, etc)?\n<!-- describe -->\n`;
  const params = new URLSearchParams({ title, body, labels: "flagged" });
  return `${REPO_URL}/issues/new?${params.toString()}`;
}

// ---- Layout -----------------------------------------------------------
// Ordered from "what is it" to "for the maintainer":
//   1. header: name, byline, badges, the description, action buttons
//   2. install (README setup notes and settings folded away)
//   3. example phrases
//   4. works with OVOS: one compact line per release channel; everything
//      technical (versions, registrations, languages, log) folded away
//   5. about this listing: assessment, facts, repo stats, tags in one block
//   6. for maintainers: README badge, request test/update, report
// Language flags appear once, in the header. Everything else names
// languages by code, and only where something is wrong.

function section(title, body, extraClass = "") {
  if (!body) return "";
  return `<section class="detail-section ${extraClass}"><h2 class="detail-subhead">${escapeHtml(title)}</h2>${body}</section>`;
}

function fold(summary, body, open = false) {
  if (!body) return "";
  return `<details class="detail-fold"${open ? " open" : ""}><summary>${summary}</summary><div class="detail-fold-body">${body}</div></details>`;
}

function renderInstall(skill) {
  const install = installInstructions(skill);
  const notes = asArray(skill.setup_notes);
  const fields = asArray(skill.settings_fields);
  const other = notPipInstallable(skill);
  if (!install && !other && !notes.length && !fields.length) return "";

  const notesHtml = notes.map((s) => `
    <div class="setup-section">
      <div class="setup-heading">${escapeHtml(s.heading)}</div>
      <pre class="setup-content">${escapeHtml(s.content)}</pre>
    </div>`).join("");
  const fieldsHtml = fields.map((f) => {
    const isApiKeyish = /api.?key|token|secret|password|credential/i.test(`${f.name} ${f.label}`);
    return `<div class="fact-row"><span class="fact-icon">${isApiKeyish ? "🔑" : "⚙️"}</span>
      <span>${escapeHtml(f.label)} <span class="fact-detail">(<code>${escapeHtml(f.name)}</code>${f.type ? `, ${escapeHtml(f.type)}` : ""})</span></span></div>`;
  }).join("");

  return section(install ? "Install" : "Setup", `
    ${other}
    ${install ? `
      <div class="install-box">
        <div class="install-label">${escapeHtml(install.label)}</div>
        <code class="install-command">${escapeHtml(install.command)}</code>
      </div>` : ""}
    ${fold(`Setup notes from the README (${notes.length})`,
      notesHtml && `<p class="setup-note">Extracted as-is from the repo's README, not verified.</p>${notesHtml}`)}
    ${fold(`Settings (${fields.length})`,
      fieldsHtml && `<p class="setup-note">Declared in the repo's <code>settingsmeta.json</code>, not verified.</p><div class="facts-list">${fieldsHtml}</div>`)}
  `);
}

function renderExamples(localized) {
  const examples = asArray(localized.examples).map((e) => `<li>"${escapeHtml(e)}"</li>`).join("");
  return examples ? section("Try saying", `<ul class="examples">${examples}</ul>`) : "";
}

// ---- Tested on OVOS ----------------------------------------------------

const FINAL = ["pass", "fail", "unsupported", "needs_device", "needs_config"];
const STATUS_TEXT = { pass: "✓ loads", unsupported: "not supported", needs_device: "needs device", needs_config: "needs config" };
const STATUS_STATE = { pass: "pass", unsupported: "unsupported", needs_device: "unsupported", needs_config: "unsupported" };

// The one line a user needs under a channel's status: what is wrong, if
// anything. Grey results and failures state their reason; a pass with
// language problems names the languages.
function compatSummaryLine(rec) {
  if (rec.status === "pass") {
    const missing = asArray(rec.languages_missing);
    if (missing.length) {
      const failed = asArray(rec.warnings).some((w) => w.startsWith("fails to load"));
      return `<span class="compat-issue">${failed ? "Fails to load with" : "No intents for"} ${missing.map((l) => `<code>${escapeHtml(l)}</code>`).join(", ")}</span>`;
    }
    const other = asArray(rec.warnings)[0];
    return other ? `<span class="compat-issue">${escapeHtml(other)}</span>` : "";
  }
  if (!rec.reason) return "";
  // "<skill_id>: why" -> "why": the page is already about this skill.
  let reason = rec.reason;
  for (const pid of asArray(rec.plugin_ids)) {
    if (reason.startsWith(`${pid}: `)) reason = reason.slice(pid.length + 2);
  }
  const cls = rec.status === "fail" ? "compat-issue compat-issue-fail" : "compat-issue";
  return `<span class="${cls}">${escapeHtml(reason.charAt(0).toUpperCase() + reason.slice(1))}</span>`;
}

function compatDetails(rec, meta) {
  const stack = (meta.stack && meta.stack.packages) || {};
  const stackText = ["ovos-core", "ovos-workshop", "ovos-padatious", "ovos-bus-client"]
    .filter((p) => stack[p]).map((p) => `${p} ${stack[p]}`).join(" · ");
  const regs = rec.registrations || {};
  const regText = Object.entries(regs).filter(([k]) => k !== "other")
    .map(([k, v]) => `${k.replace("_", " ")} (${v})`).join(" · ");
  const booted = asArray(rec.languages_booted);
  const missing = new Set(asArray(rec.languages_missing).map((l) => l.toLowerCase()));
  const langs = booted.length > 1 ? booted.map((l) =>
    `<code class="${missing.has(l.toLowerCase()) ? "compat-lang-missing" : ""}">${escapeHtml(l)}</code>`).join(" ") : "";
  return `
    <div class="compat-facts">
      ${renderStatRow("Level reached", escapeHtml(COMPAT_LEVEL_TEXT[rec.level] || ""))}
      ${renderStatRow("Tested against", escapeHtml(stackText))}
      ${regText ? renderStatRow("Registered", escapeHtml(regText)) : ""}
      ${langs ? renderStatRow("Languages", langs) : ""}
      ${rec.driver ? renderStatRow("Test driver", escapeHtml(rec.driver)) : ""}
    </div>
    ${renderRouting(rec, meta)}
    ${renderKlondike(rec, meta)}
    ${showLog(rec) ? `<pre class="compat-log">${escapeHtml(rec.log_excerpt)}</pre>` : ""}
  `;
}

// Level 3: which of the skill's utterances reach it with the OVOS
// installer's default skills loaded. Golden (hand-written) and generated
// rows are separate runs; generated ones stay hidden until
// COMPAT_PUBLIC_GENERATED (ovoscope#224).
const MISS_TEXT = {
  baseline: (m) => `taken by <code>${escapeHtml(m.taken_by || "?")}</code>${m.stage && !/^last message/.test(m.stage) ? ` (via ${escapeHtml(m.stage)})` : ""}`,
  wrong_intent: (m) => `reached another intent${m.fired && m.fired.length ? ` (<code>${escapeHtml(m.fired[0])}</code>)` : ""}`,
  // A pipeline stage that is not a fallback took the sentence without a
  // skill (OCP, persona, the reading pipeline): that is theft too, and
  // should read as such, not as "nobody".
  unhandled: (m) => stageTook(m.stage)
    ? `taken by the <code>${escapeHtml(m.stage)}</code> pipeline stage, not a skill`
    : `not handled by any skill${m.stage ? ` (stopped at ${escapeHtml(m.stage)})` : ""}`,
  hang: (m) => `not handled by any skill; a later stage never answered${m.stage ? ` (${escapeHtml(m.stage)})` : ""}`,
};

function stageTook(stage) {
  return !!stage && !/fallback|^last message|stop-pipeline/.test(stage);
}

function renderRoutingRun(title, r, takenBy = "a default skill") {
  if (!r) return "";
  if (r.status !== "ok") {
    return renderStatRow(title, escapeHtml(r.reason || "not run"));
  }
  const parts = [`${r.hit}/${r.counted} reach the skill`];
  if (r.asked) parts.push(`${r.asked} of them ask a follow-up question (answered with “cancel”)`);
  if (r.baseline) parts.push(`${r.baseline} taken by ${takenBy}`);
  if (r.wrong_intent) parts.push(`${r.wrong_intent} reach another of its intents`);
  if (r.unhandled) parts.push(`${r.unhandled} not handled by a skill`);
  if (r.hang) parts.push(`${r.hang} stuck in a later stage`);
  if (r.manual) parts.push(`${r.manual} need a human (skipped)`);
  const langs = asArray(r.langs).map((l) => `<code>${escapeHtml(l)}</code>`).join(" ");
  const notRouted = asArray(r.langs_not_routed);
  if (asArray(r.langs_partial).length) parts.push(`run stopped early in ${r.langs_partial.join(", ")}`);
  const misses = asArray(r.misses).map((m) =>
    `<li><code>${escapeHtml(m.lang || "")}</code> “${escapeHtml(m.utterance)}”: ${(MISS_TEXT[m.kind] || (() => escapeHtml(m.kind || "missed")))(m)}${m.asked ? " and asked a follow-up question" : ""}</li>`).join("");
  const collisions = asArray(r.collisions).map((m) =>
    `<li><code>${escapeHtml(m.lang || "")}</code> “${escapeHtml(m.utterance)}” went to <code>${escapeHtml(m.taken_by || "?")}</code></li>`).join("");
  return `
    ${renderStatRow(title, escapeHtml(parts.join(" · ")))}
    ${langs ? renderStatRow("Languages routed", langs + (notRouted.length ? ` <span class="setup-note">(not routed this run: ${escapeHtml(notRouted.join(", "))})</span>` : "")) : ""}
    ${misses ? `<ul class="compat-misses">${misses}</ul>` : ""}
    ${collisions ? `<p class="setup-note">Also collided with another skill tested in the same run (not counted, as neither is a default skill):</p><ul class="compat-misses">${collisions}</ul>` : ""}`;
}

function renderRouting(rec, meta) {
  const routing = rec.routing;
  if (!routing) return "";
  const route = meta.route || {};
  const rows = [];
  if (routing.install) rows.push(renderStatRow("Routing", escapeHtml(routing.install)));
  if (routing.error) rows.push(renderStatRow("Routing", escapeHtml(`not run: ${routing.error}`)));
  rows.push(renderRoutingRun("Golden utterances", routing.golden));
  if (COMPAT_PUBLIC_GENERATED) rows.push(renderRoutingRun("Generated utterances", routing.generated));
  const against = [
    asArray(route.baseline_requirements).join(", "),
    route.baseline_ids && route.baseline_ids.length ? `${route.baseline_ids.length} default skills loaded` : "",
  ].filter(Boolean).join(" · ");
  if (against) rows.push(renderStatRow("Routed against", escapeHtml(against)));
  if (asArray(route.excluded_ids).length) {
    rows.push(renderStatRow("Left out", escapeHtml(`${route.excluded_ids.join(", ")} (waits for device services, so it cannot finish loading in the test core)`)));
  }
  if (routing.ref) rows.push(renderStatRow("Utterances from", `<code>${escapeHtml(routing.ref)}</code>`));
  return `<h4 class="compat-subhead">Routing (level 3)</h4><div class="compat-facts">${rows.join("")}</div>`;
}

// Level 3 against the Klondike profile (#13): the installer's defaults plus
// its extra skills plus the curated list in compat/klondike-profile.toml.
// A worst case next to "normal install" above; it never changes the level
// or the badge.
function klondikeMeta(channel) {
  return (compatDoc && compatDoc.klondike && compatDoc.klondike[channel]) || null;
}

function collisionList(items, text) {
  return asArray(items).map((c) =>
    `<li><code>${escapeHtml(c.lang || "")}</code> “${escapeHtml(c.utterance || "")}” ${text(c)}</li>`).join("");
}

function renderKlondike(rec, meta) {
  const kmeta = klondikeMeta(rec.channel);
  if (!kmeta) return "";
  const job = kmeta.job || {};
  const res = (job.results || {})[rec.id];
  const refused = (job.refused || {})[rec.id];
  if (refused) {
    return `<h4 class="compat-subhead">Routing on a well-equipped install (Klondike profile)</h4>
      <div class="compat-facts">${renderStatRow("Install", escapeHtml(refused))}</div>`;
  }
  if (!res) return "";
  const k = res.routing || {};
  const member = res.member;
  const memberIds = new Set(asArray(job.member_skill_ids));
  const profile = kmeta.profile || {};
  const rows = [];
  { // this skill's own rows, with the profile loaded
    if (k.install) rows.push(renderStatRow("Routing", escapeHtml(k.install)));
    if (k.error) rows.push(renderStatRow("Routing", escapeHtml(`not run: ${k.error}`)));
    rows.push(renderRoutingRun("Golden utterances", k.golden, "a profile skill"));
    if (COMPAT_PUBLIC_GENERATED) rows.push(renderRoutingRun("Generated utterances", k.generated, "a profile skill"));
    // Taken by a skill the normal install does not have: say so, it is
    // what a user of both would want to know ("pick one").
    const defaults = new Set(asArray((meta.route || {}).baseline_ids));
    const added = new Set(asArray(profile.added_stages).map((st) => st.replace(/-(high|medium|low)$/, "")));
    const overlaps = [...new Set(asArray((k.golden || {}).misses)
      .filter((m) => (m.kind === "baseline" && m.taken_by && !defaults.has(m.taken_by))
        || (m.kind === "unhandled" && added.has(m.stage)))
      .map((m) => (m.kind === "baseline" ? m.taken_by : m.stage)))];
    if (overlaps.length) {
      rows.push(renderStatRow("Overlaps with", overlaps.map((o) => `<code>${escapeHtml(o)}</code>`).join(" ")
        + ` <span class="setup-note">(in the Klondike profile, not in a normal install)</span>`));
    }
  }
  if (member) {
    const cur = asArray(profile.curated).find((c) => c.id === rec.id);
    rows.push(renderStatRow("In the profile", escapeHtml(cur ? `yes, curated: ${cur.function || ""}` : "yes, installed by the OVOS installer")));
    const own = k.golden || {};
    const inside = asArray(own.misses).filter((m) => m.kind === "baseline" && memberIds.has(m.taken_by));
    const takenBy = collisionList(inside, (c) => `taken by <code>${escapeHtml(c.taken_by || "?")}</code>`);
    const takesFrom = collisionList((((job.takes_from || {})[rec.id]) || {}).golden, (c) => `(a sentence of <code>${escapeHtml(c.from || "?")}</code>)`);
    if (takenBy || takesFrom) {
      rows.push(`<p class="setup-note">Collides within the profile (all profile skills in one core):</p>`
        + (takenBy ? `<ul class="compat-misses">${takenBy}</ul>` : "")
        + (takesFrom ? `<p class="setup-note">Takes these from other profile skills:</p><ul class="compat-misses">${takesFrom}</ul>` : ""));
    } else if (own.status === "ok") {
      rows.push(renderStatRow("Within the profile", "no collisions in its golden utterances"));
    }
  }
  // Klondike-test reports (#13): reports from a device that runs the
  // profile, with the same currency rules as any report (#11).
  const people = ((reportsDoc && reportsDoc.entries && reportsDoc.entries[rec.id]) || {})[rec.channel] || {};
  const pm = people.maintainer;
  const pc = people.community || {};
  const kparts = [];
  if (pm && pm.status === "current" && pm.klondike) kparts.push(`${pm.passes ? "✓" : "✗"} maintainer`);
  if (pc.klondike_works) kparts.push(`✓ ${pc.klondike_works} ${pc.klondike_works === 1 ? "user" : "users"}`);
  if (kparts.length) {
    rows.push(renderStatRow("On a real Klondike-profile device", escapeHtml(kparts.join(" · "))));
  } else if (pm && pm.status === "current" && pm.klondike_reason) {
    rows.push(renderStatRow("Maintainer's device", escapeHtml(`not a Klondike-profile device: ${pm.klondike_reason}`)));
  }
  if (asArray(profile.added_stages).length) {
    rows.push(renderStatRow("Pipeline", `the profile adds ${asArray(profile.added_stages).map((s) => `<code>${escapeHtml(s)}</code>`).join(" ")} to the installer's pipeline`));
  }
  rows.push(renderStatRow("Profile", `<a href="for-maintainers.html#klondike-profile">what is in it, and how to propose a skill</a>`));
  return `<h4 class="compat-subhead">Routing on a well-equipped install (Klondike profile)</h4>
    <p class="setup-note">A worst case: the installer's default and extra skills plus a curated set, all loaded together. It does not change the level or the badge.</p>
    <div class="compat-facts">${rows.join("")}</div>`;
}

// The log only helps when something went wrong: a failure, a grey result,
// or languages that fail to load. For a clean pass it is just INFO noise.
function showLog(rec) {
  if (!rec.log_excerpt) return false;
  if (rec.status !== "pass") return true;
  return asArray(rec.warnings).some((w) => w.startsWith("fails to load"));
}

function renderWorksWith(skill) {
  const results = (compatDoc && compatDoc.results && compatDoc.results[skill.id]) || {};
  // The feed's compat field arrives with the next crawl (up to 3h after a
  // test run); results.json is fresh immediately, so either is enough.
  const people = reportChannels(skill);
  if (!skill.compat && Object.keys(results).length === 0 && !people.length) return "";
  const channelsMeta = (compatDoc && compatDoc.channels) || {};
  const compat = skill.compat || { channels: {} };
  const channels = COMPAT_CHANNELS.filter((ch) => results[ch] || channelsMeta[ch] || people.includes(ch));

  const rows = channels.map((ch) => {
    const rec = results[ch];
    if (!rec || !FINAL.includes(rec.status)) {
      return `
        <div class="compat-row">
          <div class="compat-row-head"><strong>${escapeHtml(ch)}</strong>
            <span class="compat-label compat-untested">not tested here yet</span></div>
          ${renderPeopleReports(skill, ch)}
        </div>`;
    }
    const c = (compat.channels || {})[ch] || {};
    const text = c.label || STATUS_TEXT[rec.status] || (rec.level === 0 ? "✗ doesn't install" : "✗ doesn't load");
    const state = c.state || STATUS_STATE[rec.status] || "fail";
    const version = rec.version_tested || rec.requested_version || "";
    const meta = [version && `v${version}${rec.channel_pinned ? " (channel's version)" : ""}`,
      formatDate(rec.tested_at)].filter(Boolean).join(" · ");
    return `
      <div class="compat-row">
        <div class="compat-row-head">
          <strong>${escapeHtml(ch)}</strong>
          <span class="compat-label compat-${escapeHtml(state)}">${escapeHtml(text)}</span>
          <span class="compat-meta">${escapeHtml(meta)}</span>
        </div>
        ${compatSummaryLine(rec)}
        ${fold("Test details", compatDetails(rec, channelsMeta[ch] || {}))}
        ${renderPeopleReports(skill, ch)}
      </div>`;
  }).join("");

  return section("Tested on OVOS", `
    ${rows || `<p class="setup-note">Not tested yet. It's queued for the next nightly run.</p>`}
    <p class="setup-note compat-footnote">Our own tests install each release channel's own package versions and start the skill in a test core with all its languages. Reports from the maintainer and from users are shown as such, never as our result. <a href="for-maintainers.html#labels">What the labels mean</a> · <a href="for-maintainers.html#channel-tests">How testing works</a></p>
    ${renderReportBox(skill)}
  `);
}

// ---- About this listing ------------------------------------------------

function assessmentHeadline(skill) {
  if (skill.component_type === "Infrastructure") {
    return `No completeness rating: this is ecosystem tooling or infrastructure, not something meant to be <code>pip install</code>ed.`;
  }
  if (skill.tier === 1) {
    if (skill.on_pypi && skill.has_release) return `<strong>Looks Complete</strong>: a confirmed manifest, published on PyPI, with a GitHub release.`;
    if (skill.in_ovos_store) return `<strong>Looks Complete</strong>: listed in OVOS's own upcoming Skill Store, which a maintainer reviewed.`;
    return `<strong>Looks Complete</strong>.`;
  }
  if (skill.tier === 2) return `<strong>Incomplete</strong>: a confirmed manifest, but not everything is published (see below).`;
  return `<strong>Inferred, Unconfirmed</strong>: no formal manifest was found; what's shown is guessed from the repo's tags, description and code.`;
}

function renderAbout(skill) {
  const infra = skill.component_type === "Infrastructure";
  const facts = [
    ...(!infra ? [
      { label: "Published on PyPI", ok: skill.on_pypi, detail: skill.on_pypi ? `${skill.package_name} ${skill.pypi_version}` : null },
      { label: "Has a GitHub release", ok: skill.has_release },
    ] : []),
    { label: "In OVOS's upcoming Skill Store", ok: skill.in_ovos_store },
    { label: "License", ok: !!skill.license, detail: skill.license || "none declared" },
    { label: "Not archived", ok: !skill.archived },
  ];
  const factsHtml = facts.map((f) => `
    <div class="fact-row"><span class="fact-icon">${f.ok ? "✅" : "❌"}</span>
      <span>${escapeHtml(f.label)}${f.detail ? ` <span class="fact-detail">(${escapeHtml(f.detail)})</span>` : ""}</span></div>`).join("");
  const tags = asArray(skill.tags).map((t) => `<span class="tag">${escapeHtml(t)}</span>`).join("");

  return section("About this listing", `
    <p class="assessment-text">${assessmentHeadline(skill)}</p>
    <div class="about-grid">
      <div class="facts-list">${factsHtml}</div>
      <div class="stat-grid stat-grid-compact">
        ${renderStatRow("Type", escapeHtml(skill.component_type || ""))}
        ${renderStatRow("Created", escapeHtml(formatDate(skill.repo_created_at) || ""))}
        ${renderStatRow("Last updated", escapeHtml(formatDate(skill.last_updated) || ""))}
        ${renderStatRow("Stars", skill.stars)}
        ${renderStatRow("Forks", skill.forks)}
        ${renderStatRow("Open issues", skill.open_issues)}
      </div>
    </div>
    ${renderLicenseWarning(skill)}
    ${tags ? `<div class="tags about-tags">${tags}</div>` : ""}
  `);
}

// ---- For maintainers ---------------------------------------------------

function renderMaintainers(skill) {
  const results = (compatDoc && compatDoc.results && compatDoc.results[skill.id]) || {};
  const badgeId = (skill.compat && skill.compat.badge_id) || skill.skill_id || skill.id;
  const snippets = COMPAT_CHANNELS
    .filter((ch) => results[ch] && FINAL.includes(results[ch].status))
    .map((ch) => {
      const img = `https://img.shields.io/endpoint?url=${PAGES_URL}/badges/${badgeId}/${ch}.json`;
      const md = `[![OVOS ${ch}](${img})](${PAGES_URL}/detail.html?id=${encodeURIComponent(skill.id)})`;
      return `<div class="compat-snippet"><img src="${escapeHtml(img)}" alt="OVOS ${escapeHtml(ch)} badge" loading="lazy"><code class="install-command">${escapeHtml(md)}</code></div>`;
    }).join("");

  // Grey results: we could not judge it here, but the maintainer can on a
  // real device (#6, "needs a report" hints).
  const grey = COMPAT_CHANNELS.filter((ch) => results[ch] && ["needs_config", "needs_device", "unsupported"].includes(results[ch].status));
  const hint = grey.length ? `
      <div class="report-hint">
        <strong>This can't be tested automatically on ${escapeHtml(grey.join(" and "))}.</strong>
        You can test it on your own configured device and publish the report in your repo as
        <code>test/reports/&lt;channel&gt;.json</code>; it then shows here as maintainer-tested.
        <a href="for-maintainers.html#device-reports">How to</a>
      </div>` : "";

  return `
    <section class="detail-section maintainer-section">
      <h2 class="detail-subhead">For the maintainer</h2>
      ${hint}
      ${fold("README badge", snippets && `<p class="setup-note">Paste into your README. It updates by itself after every test run.</p>${snippets}`)}
      <div class="detail-meta-links">
        ${skill.compat ? `<a href="${testRequestUrl(skill)}" target="_blank" rel="noopener">🧪 Request test</a>` : ""}
        <a href="${updateRequestUrl(skill)}" target="_blank" rel="noopener">🔄 Request update</a>
        <a href="for-maintainers.html">📖 Guide for maintainers</a>
        <a href="${flagUrl(skill)}" target="_blank" rel="noopener" class="flag-link">🚩 Report a problem</a>
      </div>
    </section>`;
}

// ---- Page ---------------------------------------------------------------

function renderDetail(skill) {
  const localized = localizeSkill(skill, currentSiteLang);
  document.title = `${localized.name} · OVOS Klondike Mercantile`;

  const fallbackIcon = genericIconFor(skill);
  const icon = skill.icon || fallbackIcon;
  const untranslatedNote = (currentSiteLang !== "en-us" && !localized.translated)
    ? `<div class="untranslated-note">Not yet translated - showing English</div>` : "";

  detailRoot.innerHTML = `
    <div class="detail-card">
      <div class="detail-top">
        <img src="${escapeHtml(icon)}" alt="" class="detail-icon${skill.icon ? iconExtras(skill).cls : ""}"${skill.icon ? iconExtras(skill).style : ""}
             onerror="this.onerror=null;this.className='detail-icon';this.removeAttribute('style');this.src='${fallbackIcon}'">
        <div>
          <h1>${escapeHtml(localized.name)}</h1>
          <div class="byline">by ${escapeHtml(skill.author)}${versionLabel(skill) ? ` · ${escapeHtml(versionLabel(skill))}` : ""}</div>
          ${renderLanguageFlags(skill, currentSiteLang)}
          ${untranslatedNote}
        </div>
      </div>

      <div class="badges">${renderBadges(skill)}</div>
      ${renderArchivedWarning(skill)}

      <p class="detail-description">${escapeHtml(localized.description || "No description available.")}</p>

      <div class="detail-links">
        <a href="${escapeHtml(skill.source)}" target="_blank" rel="noopener" class="detail-link-btn">View on GitHub</a>
        ${skill.package_name && skill.on_pypi ? `<a href="https://pypi.org/project/${escapeHtml(skill.package_name)}/" target="_blank" rel="noopener" class="detail-link-btn">View on PyPI</a>` : ""}
        ${skill.in_ovos_localize ? `<a href="https://openvoiceos.github.io/ovos-localize/" target="_blank" rel="noopener" class="detail-link-btn detail-link-translate">Help Translate</a>` : ""}
      </div>

      ${renderInstall(skill)}
      ${renderExamples(localized)}
      ${renderWorksWith(skill)}
      ${renderAbout(skill)}
      ${renderMaintainers(skill)}
    </div>
  `;
  wireReportBox(skill);
}

// ?skill=<skill_id>: many entries have no skill_id (only when their
// skill.json names it), so also try the OVOS convention
// "<package>.<author>" against the entry's package and owner, and last the
// package the report itself names (a #report= link from ovos-tui).
function normPkg(name) {
  return String(name || "").toLowerCase().replace(/[-_.]+/g, "-");
}

async function findBySkillId(all, sid) {
  if (!sid) return null;
  // skill.json's skill_id sometimes carries an entry point ("x.y=module:Class")
  const own = (s) => String(s.skill_id || "").toLowerCase().split("=")[0].trim();
  const exact = all.find((s) => own(s) === sid);
  if (exact) return exact;
  const cut = sid.lastIndexOf(".");
  if (cut > 0) {
    const base = sid.slice(0, cut);
    const author = sid.slice(cut + 1);
    // older OVOS skills are "skill-ovos-x.openvoiceos" in package "ovos-skill-x"
    const names = new Set([base, base.replace(/^skill-ovos-/, "ovos-skill-")].map(normPkg));
    const candidates = all.filter((s) => names.has(normPkg(s.package_name)) ||
      [...names].some((n) => s.id.toLowerCase() === `${author}-${n}`));
    const byOwner = candidates.find((s) => s.id.toLowerCase().startsWith(`${author}-`));
    if (byOwner || candidates.length === 1) return byOwner || candidates[0];
  }
  if (typeof reportFromLink === "function") {
    try {
      const report = JSON.parse(await reportFromLink());
      const info = (((report || {}).manifest || {}).skills || {})[sid] || {};
      const matches = all.filter((s) => info.package && normPkg(s.package_name) === normPkg(info.package));
      if (matches.length === 1) return matches[0];
    } catch (e) { /* no or unreadable report */ }
  }
  return null;
}

const params = new URLSearchParams(window.location.search);
const wantedId = params.get("id");
// ?skill=<skill_id> (e.g. from an ovos-tui report link) finds the entry by its OVOS skill id
const wantedSkill = (params.get("skill") || "").toLowerCase();

if (!wantedId && !wantedSkill) {
  detailRoot.innerHTML = `<p class="loading">No skill specified. <a href="index.html">Back to the store</a>.</p>`;
} else {
  const cacheBust = `?t=${Date.now()}`;
  // Channel test results are optional: a missing or broken results.json
  // must never stop the page from rendering.
  const compatLoad = loadCompatResults(cacheBust).then((doc) => { compatDoc = doc; });
  const reportsLoad = loadReportsIndex(cacheBust).then((doc) => { reportsDoc = doc; });
  Promise.all([fetch(`skills.json${cacheBust}`, { cache: "no-store" }), compatLoad, reportsLoad])
    .then(([res]) => {
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      return res.json();
    })
    .then(async (data) => {
      const all = applyReports(applyCompatResults(data, compatDoc), reportsDoc);
      const skill = wantedId ? all.find((s) => s.id === wantedId) : await findBySkillId(all, wantedSkill);
      if (!skill) {
        detailRoot.innerHTML = `<p class="loading">Couldn't find that entry - it may have been removed in a later update. <a href="index.html">Back to the store</a>.</p>`;
        return;
      }
      currentSkill = skill;
      // one address per entry: ?skill= and a #report= link become ?id= (the
      // report itself was read before, see REPORT_LINK in detail-reports.js)
      if (wantedSkill || window.location.hash) {
        history.replaceState(null, "", `detail.html?id=${encodeURIComponent(skill.id)}`);
      }
      populateSiteLangSelect(siteLangSelect);
      siteLangSelect.addEventListener("change", () => {
        currentSiteLang = siteLangSelect.value;
        setSiteLanguage(currentSiteLang);
        renderDetail(currentSkill);
      });
      renderDetail(skill);
    })
    .catch((err) => {
      detailRoot.innerHTML = `<p class="loading">Could not load data (${escapeHtml(err.message)}). <a href="index.html">Back to the store</a>.</p>`;
    });
}
