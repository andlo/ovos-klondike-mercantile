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

function installInstructions(skill) {
  if (skill.on_pypi && skill.package_name) {
    return {
      label: "Install from PyPI",
      command: `pip install ${skill.package_name}`,
    };
  }
  if (skill.source) {
    return {
      label: "Install from GitHub (not on PyPI)",
      command: `pip install git+${skill.source}.git`,
    };
  }
  return null;
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

function renderSetupNotes(skill) {
  const sections = asArray(skill.setup_notes);
  if (sections.length === 0) return "";
  const blocks = sections.map((s) => `
    <div class="setup-section">
      <div class="setup-heading">${escapeHtml(s.heading)}</div>
      <pre class="setup-content">${escapeHtml(s.content)}</pre>
    </div>
  `).join("");
  return `
    <h2 class="detail-subhead">Additional setup / configuration</h2>
    <p class="setup-note">
      Pulled straight from the repo's own README - may include steps
      beyond a plain install (editing <code>mycroft.conf</code>,
      enabling a service, setting an API key, etc). Not verified,
      just extracted as-is.
    </p>
    ${blocks}
  `;
}

function renderAssessment(skill) {
  let headline;
  if (skill.component_type === "Infrastructure") {
    headline = `Not given a completeness tier - this is OVOS-ecosystem tooling/infrastructure (docs, the official Skill Store's own data, an installer, etc), not something meant to be <code>pip install</code>ed. The "Looks Complete"/"Incomplete" system checks for a PyPI package and a GitHub release, which isn't a meaningful measure of completeness for this kind of repo.`;
  } else if (skill.tier === 1) {
    if (skill.on_pypi && skill.has_release) {
      headline = `Rated <strong>Looks Complete</strong> - it has a confirmed manifest (a proper <code>skill.json</code> or plugin entry-point declaration), is published on PyPI, and has a GitHub release.`;
    } else if (skill.in_ovos_store) {
      const gaps = [];
      if (!skill.on_pypi) gaps.push("isn't published on PyPI");
      if (!skill.has_release) gaps.push("has no GitHub release");
      const gapsText = gaps.length ? ` even though it ${gaps.join(" and ")}` : "";
      headline = `Rated <strong>Looks Complete</strong> primarily because it's already listed in OVOS's own upcoming Skill Store - a maintainer reviewed and merged it there, which counts as a strong completeness signal on its own${gapsText}.`;
    } else {
      headline = `Rated <strong>Looks Complete</strong>.`;
    }
  } else if (skill.tier === 2) {
    const missing = [];
    if (!skill.on_pypi) missing.push("isn't published on PyPI");
    if (!skill.has_release) missing.push("has no GitHub release");
    headline = `Rated <strong>Incomplete</strong> - it has a confirmed manifest (a proper <code>skill.json</code> or plugin entry-point declaration), but it ${missing.join(" and ")}.`;
  } else {
    headline = `Rated <strong>Inferred, Unconfirmed</strong> - no formal manifest (a <code>skill.json</code>, or a declared plugin entry-point) was found for this repo. Everything shown is guessed from the repo's own topic tags, description, and code, not a confirmed declaration.`;
  }

  const facts = [
    ...(skill.component_type !== "Infrastructure" ? [
      {
        label: "Published on PyPI",
        ok: skill.on_pypi,
        detail: skill.on_pypi ? `as ${skill.package_name}, v${skill.pypi_version}` : null,
      },
      { label: "Has a GitHub release", ok: skill.has_release },
    ] : []),
    { label: "Listed in OVOS's upcoming Skill Store", ok: skill.in_ovos_store },
    { label: "Has a declared license", ok: !!skill.license, detail: skill.license },
    { label: "Not archived", ok: !skill.archived },
  ];
  const factsHtml = facts.map((f) => `
    <div class="fact-row">
      <span class="fact-icon">${f.ok ? "✅" : "❌"}</span>
      <span>${escapeHtml(f.label)}${f.detail ? ` <span class="fact-detail">(${escapeHtml(f.detail)})</span>` : ""}</span>
    </div>
  `).join("");

  return `
    <h2 class="detail-subhead">Why this assessment?</h2>
    <p class="assessment-text">${headline}</p>
    <div class="facts-list">${factsHtml}</div>
  `;
}

function renderSettings(skill) {
  const fields = asArray(skill.settings_fields);
  if (fields.length === 0) return "";
  const rows = fields.map((f) => {
    const isApiKeyish = /api.?key|token|secret|password|credential/i.test(`${f.name} ${f.label}`);
    return `
      <div class="fact-row">
        <span class="fact-icon">${isApiKeyish ? "🔑" : "⚙️"}</span>
        <span>${escapeHtml(f.label)} <span class="fact-detail">(<code>${escapeHtml(f.name)}</code>${f.type ? `, ${escapeHtml(f.type)}` : ""})</span></span>
      </div>
    `;
  }).join("");
  return `
    <h2 class="detail-subhead">Configurable settings</h2>
    <p class="setup-note">
      From this repo's own <code>settingsmeta.json</code> - shown as
      declared, not verified to actually work.
    </p>
    <div class="facts-list">${rows}</div>
  `;
}

const REPO_URL = "https://github.com/andlo/ovos-klondike-mercantile";

// Both open GitHub's own "new issue" form, pre-filled - no backend
// needed on this static site. A maintainer (or an automated workflow
// watching for these labels, if one gets built later) can then bump
// the repo to the front of the rotation, matching the same effect as
// manually removing it from state.json's "attempted" list.
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

function renderDetail(skill) {
  const localized = localizeSkill(skill, currentSiteLang);
  document.title = `${localized.name} · OVOS Klondike Mercantile`;

  const fallbackIcon = genericIconFor(skill);
  const icon = skill.icon || fallbackIcon;
  const install = installInstructions(skill);
  const examples = asArray(localized.examples)
    .map((e) => `<li>"${escapeHtml(e)}"</li>`).join("");
  const tags = asArray(skill.tags)
    .map((t) => `<span class="tag">${escapeHtml(t)}</span>`).join("");

  const createdDate = formatDate(skill.repo_created_at);
  const updatedDate = formatDate(skill.last_updated);
  const untranslatedNote = (currentSiteLang !== "en-us" && !localized.translated)
    ? `<div class="untranslated-note">Not yet translated - showing English</div>`
    : "";

  detailRoot.innerHTML = `
    <div class="detail-card">
      <div class="detail-top">
        <img src="${escapeHtml(icon)}" alt="" class="detail-icon"
             onerror="this.onerror=null;this.src='${fallbackIcon}'">
        <div>
          <h1>${escapeHtml(localized.name)}</h1>
          <div class="byline">by ${escapeHtml(skill.author)}${versionLabel(skill) ? ` · ${escapeHtml(versionLabel(skill))}` : ""}</div>
          ${renderLanguageFlags(skill, currentSiteLang)}
          ${untranslatedNote}
        </div>
      </div>

      <div class="badges">${renderBadges(skill)}</div>

      ${renderAssessment(skill)}

      ${renderLicenseWarning(skill)}

      ${renderArchivedWarning(skill)}

      <p class="detail-description">${escapeHtml(localized.description || "No description available.")}</p>

      ${install ? `
        <div class="install-box">
          <div class="install-label">${escapeHtml(install.label)}</div>
          <code class="install-command">${escapeHtml(install.command)}</code>
        </div>
      ` : ""}

      ${renderSetupNotes(skill)}

      ${renderSettings(skill)}

      ${examples ? `
        <h2 class="detail-subhead">Example phrases</h2>
        <ul class="examples">${examples}</ul>
      ` : ""}

      ${tags ? `
        <h2 class="detail-subhead">Tags</h2>
        <div class="tags">${tags}</div>
      ` : ""}

      <h2 class="detail-subhead">Repository stats</h2>
      <div class="stat-grid">
        ${renderStatRow("Type", skill.component_type)}
        ${renderStatRow("License", skill.license || "None declared")}
        ${renderStatRow("Created", createdDate)}
        ${renderStatRow("Last updated", updatedDate)}
        ${renderStatRow("Stars", skill.stars)}
        ${renderStatRow("Forks", skill.forks)}
        ${renderStatRow("Open issues", skill.open_issues)}
        ${renderStatRow("PyPI version", skill.pypi_version || "Not published")}
      </div>

      <div class="detail-links">
        <a href="${escapeHtml(skill.source)}" target="_blank" rel="noopener" class="detail-link-btn">View on GitHub</a>
        ${skill.package_name ? `<a href="https://pypi.org/project/${escapeHtml(skill.package_name)}/" target="_blank" rel="noopener" class="detail-link-btn">View on PyPI</a>` : ""}
        ${skill.in_ovos_localize ? `<a href="https://openvoiceos.github.io/ovos-localize/" target="_blank" rel="noopener" class="detail-link-btn detail-link-translate">Help Translate</a>` : ""}
      </div>

      <div class="detail-meta-links">
        <a href="${updateRequestUrl(skill)}" target="_blank" rel="noopener">🔄 Request update</a>
        <a href="${flagUrl(skill)}" target="_blank" rel="noopener" class="flag-link">🚩 Report a problem</a>
      </div>
    </div>
  `;
}

const params = new URLSearchParams(window.location.search);
const wantedId = params.get("id");

if (!wantedId) {
  detailRoot.innerHTML = `<p class="loading">No skill specified. <a href="index.html">Back to the store</a>.</p>`;
} else {
  const cacheBust = `?t=${Date.now()}`;
  fetch(`skills.json${cacheBust}`, { cache: "no-store" })
    .then((res) => {
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      return res.json();
    })
    .then((data) => {
      const skill = data.find((s) => s.id === wantedId);
      if (!skill) {
        detailRoot.innerHTML = `<p class="loading">Couldn't find that entry - it may have been removed in a later update. <a href="index.html">Back to the store</a>.</p>`;
        return;
      }
      currentSkill = skill;
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
