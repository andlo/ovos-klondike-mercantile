// Detail page (detail.html) - reads ?id= from the URL, fetches the
// same skills.json the index page uses, and renders one entry in
// full: complete (untruncated) description, install instructions,
// a license warning when missing, and full repo stats (created,
// last updated, stars/forks/open issues).

const detailRoot = document.getElementById("detail-root");

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
  if (skill.tier === 1) {
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
    {
      label: "Published on PyPI",
      ok: skill.on_pypi,
      detail: skill.on_pypi ? `as ${skill.package_name}, v${skill.pypi_version}` : null,
    },
    { label: "Has a GitHub release", ok: skill.has_release },
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

function renderDetail(skill) {
  document.title = `${skill.name} · OVOS Klondike Mercantile`;

  const fallbackIcon = genericIconFor(skill);
  const icon = skill.icon || fallbackIcon;
  const install = installInstructions(skill);
  const examples = asArray(skill.examples)
    .map((e) => `<li>"${escapeHtml(e)}"</li>`).join("");
  const tags = asArray(skill.tags)
    .map((t) => `<span class="tag">${escapeHtml(t)}</span>`).join("");

  const createdDate = formatDate(skill.repo_created_at);
  const updatedDate = formatDate(skill.last_updated);

  detailRoot.innerHTML = `
    <div class="detail-card">
      <div class="detail-top">
        <img src="${escapeHtml(icon)}" alt="" class="detail-icon"
             onerror="this.onerror=null;this.src='${fallbackIcon}'">
        <div>
          <h1>${escapeHtml(skill.name)}</h1>
          <div class="byline">by ${escapeHtml(skill.author)}${skill.pypi_version ? ` · v${escapeHtml(skill.pypi_version)}` : " · unreleased"}</div>
          ${renderLanguageFlags(skill)}
        </div>
      </div>

      <div class="badges">${renderBadges(skill)}</div>

      ${renderAssessment(skill)}

      ${renderLicenseWarning(skill)}

      ${renderArchivedWarning(skill)}

      <p class="detail-description">${escapeHtml(skill.description || "No description available.")}</p>

      ${install ? `
        <div class="install-box">
          <div class="install-label">${escapeHtml(install.label)}</div>
          <code class="install-command">${escapeHtml(install.command)}</code>
        </div>
      ` : ""}

      ${renderSetupNotes(skill)}

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
      renderDetail(skill);
    })
    .catch((err) => {
      detailRoot.innerHTML = `<p class="loading">Could not load data (${escapeHtml(err.message)}). <a href="index.html">Back to the store</a>.</p>`;
    });
}
