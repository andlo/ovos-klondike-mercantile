// Index page (index.html) specific logic - shared constants/helpers
// (badges, icons, escapeHtml, etc) live in shared.js, loaded before
// this file.

const grid = document.getElementById("grid");
const newSection = document.getElementById("new-section");
const newGrid = document.getElementById("new-grid");
const emptyState = document.getElementById("empty-state");
const statsLine = document.getElementById("stats-line");
const queueLine = document.getElementById("queue-line");
const searchInput = document.getElementById("search");
const siteLangSelect = document.getElementById("site-lang");
const sortOrder = document.getElementById("sort-order");
const showArchivedToggle = document.getElementById("show-archived");
const statsContent = document.getElementById("stats-content");

let skills = [];
let currentSiteLang = getSiteLanguage();

function renderCard(skill) {
  const localized = localizeSkill(skill, currentSiteLang);
  const examples = asArray(localized.examples).slice(0, 3)
    .map((e) => `<li>"${escapeHtml(e)}"</li>`).join("");
  const tags = asArray(skill.tags)
    .map((t) => `<span class="tag">${escapeHtml(t)}</span>`).join("");
  const fallbackIcon = genericIconFor(skill);
  const icon = skill.icon || fallbackIcon;
  const version = versionLabel(skill);
  const description = truncate(localized.description, MAX_DESCRIPTION_LENGTH);
  const stats = [];
  if (skill.stars) stats.push(`⭐ ${skill.stars}`);
  if (skill.forks) stats.push(`🍴 ${skill.forks}`);
  const statsLine = stats.length ? `<div class="stats">${stats.join(" · ")}</div>` : "";
  const detailUrl = `detail.html?id=${encodeURIComponent(skill.id)}`;
  // Shown only when the display language isn't English AND this
  // specific skill has no translation for it - not shown at all in
  // English (there's nothing to fall back FROM), and not shown for
  // skills that DO have a real translation.
  const untranslatedNote = (currentSiteLang !== "en-us" && !localized.translated)
    ? `<div class="untranslated-note">Not yet translated - showing English</div>`
    : "";

  return `
    <article class="card tier-${skill.tier}">
      <a class="card-link" href="${escapeHtml(detailUrl)}">
        <div class="card-head">
          <img src="${escapeHtml(icon)}" alt="" loading="lazy" class="card-icon${skill.icon ? iconExtras(skill).cls : ""}"${skill.icon ? iconExtras(skill).style : ""}
               onerror="this.onerror=null;this.className='card-icon';this.removeAttribute('style');this.src='${fallbackIcon}'">
          <div class="card-head-text">
            <h2>${escapeHtml(localized.name)}</h2>
            <div class="byline">by ${escapeHtml(skill.author)}${version ? ` · ${escapeHtml(version)}` : ""}</div>
            ${statsLine}
            ${renderLanguageFlags(skill, currentSiteLang)}
            ${untranslatedNote}
          </div>
        </div>
        <div class="badges">${renderBadges(skill)}</div>
        ${renderCompatLabels(skill) || renderQualityLabel(skill) ? `<div class="compat-labels">${renderQualityLabel(skill)}${renderCompatLabels(skill)}</div>` : ""}
        <p class="description">${escapeHtml(description)}</p>
        <ul class="examples">${examples}</ul>
        <div class="tags">${tags}</div>
      </a>
      <div class="links">
        <a href="${escapeHtml(skill.source)}" target="_blank" rel="noopener">GitHub</a>
        ${skill.package_name ? `<a href="https://pypi.org/project/${escapeHtml(skill.package_name)}/" target="_blank" rel="noopener">PyPI</a>` : ""}
        ${skill.in_ovos_localize ? `<a href="https://openvoiceos.github.io/ovos-localize/" target="_blank" rel="noopener" class="translate-link">Translate</a>` : ""}
      </div>
    </article>
  `;
}

function sortSkills(list, order) {
  const sorted = [...list];
  if (order === "recommended") {
    sorted.sort((a, b) => recommendedRank(b) - recommendedRank(a) || (b.stars || 0) - (a.stars || 0));
  } else if (order === "stars") {
    sorted.sort((a, b) => (b.stars || 0) - (a.stars || 0));
  } else if (order === "newest") {
    sorted.sort((a, b) => new Date(b.last_updated || 0) - new Date(a.last_updated || 0));
  } else {
    sorted.sort((a, b) =>
      (localizeSkill(a, currentSiteLang).name || "").localeCompare(localizeSkill(b, currentSiteLang).name || "")
    );
  }
  return sorted;
}

function groupByCategory(list) {
  // Skills group by their inferred content category (Education,
  // Utility, ...); everything else groups by its own component type
  // (OCP Media Plugin, Pipeline Plugin, Persona, ...) instead of
  // being lumped into a generic "Other" bucket alongside them.
  const groups = new Map();
  for (const skill of list) {
    const key = (skill.component_type && skill.component_type !== "Skill")
      ? skill.component_type
      : (skill.category || "Other");
    if (!groups.has(key)) groups.set(key, []);
    groups.get(key).push(skill);
  }
  return new Map(
    [...groups.entries()].sort(([a], [b]) => {
      if (a === "Other") return 1;
      if (b === "Other") return -1;
      return a.localeCompare(b);
    })
  );
}

function render(list) {
  if (list.length === 0) {
    grid.innerHTML = "";
    emptyState.hidden = false;
    return;
  }
  emptyState.hidden = true;

  const groups = groupByCategory(list);
  let html = "";
  for (const [category, members] of groups) {
    html += `
      <section class="group">
        <h2 class="group-title">${escapeHtml(category)}</h2>
        <div class="card-grid">${members.map(renderCard).join("")}</div>
      </section>
    `;
  }
  grid.innerHTML = html;
}

const MAX_NEW_ITEMS = 8;

function renderNewSection(list) {
  const newRepos = [...list].filter((s) => s.is_new_repo)
    .sort((a, b) => new Date(b.repo_created_at || 0) - new Date(a.repo_created_at || 0));
  const updated = [...list].filter((s) => s.is_recently_updated && !s.is_new_repo)
    .sort((a, b) => new Date(b.last_updated || 0) - new Date(a.last_updated || 0));

  if (newRepos.length === 0 && updated.length === 0) {
    newSection.hidden = true;
    return;
  }
  newSection.hidden = false;

  let html = "";
  if (newRepos.length) {
    const shown = newRepos.slice(0, MAX_NEW_ITEMS);
    const moreCount = newRepos.length - shown.length;
    html += `
      <div class="new-subsection">
        <h3 class="new-subtitle">🆕 New repos${moreCount > 0 ? ` <span class="new-count">(${shown.length} of ${newRepos.length})</span>` : ""}</h3>
        <div class="card-grid">${shown.map(renderCard).join("")}</div>
      </div>
    `;
  }
  if (updated.length) {
    const shown = updated.slice(0, MAX_NEW_ITEMS);
    const moreCount = updated.length - shown.length;
    html += `
      <div class="new-subsection">
        <h3 class="new-subtitle">🔄 Recently updated${moreCount > 0 ? ` <span class="new-count">(${shown.length} of ${updated.length})</span>` : ""}</h3>
        <div class="card-grid">${shown.map(renderCard).join("")}</div>
      </div>
    `;
  }
  newGrid.innerHTML = html;
}

function matchesSearch(skill, query) {
  if (!query) return true;
  const localized = localizeSkill(skill, currentSiteLang);
  const haystack = [
    skill.name, skill.description, localized.name, localized.description, skill.author,
    ...asArray(skill.tags), ...asArray(skill.examples), ...asArray(localized.examples),
  ].join(" ").toLowerCase();
  return haystack.includes(query);
}

const TIER_CHART_COLORS = { 1: "#1e8a4c", 2: "#b5680b", 3: "#8a8f98" };

function renderTypeTierChart(list) {
  const groups = ["Skill", "Plugin", "Tool"];
  const data = groups.map((g) => {
    const subset = list.filter((s) => s.type_group === g);
    const tiers = { 1: 0, 2: 0, 3: 0 };
    for (const s of subset) tiers[s.tier] = (tiers[s.tier] || 0) + 1;
    return { group: g, total: subset.length, tiers };
  }).filter((d) => d.total > 0);
  if (data.length === 0) return "";
  const maxTotal = Math.max(...data.map((d) => d.total), 1);

  const rows = data.map((d) => {
    const trackWidthPct = (d.total / maxTotal) * 100;
    const segments = [1, 2, 3].map((tier) => {
      const count = d.tiers[tier] || 0;
      if (count === 0) return "";
      const segWidthPct = (count / d.total) * 100;
      const label = TIER_META[tier].label;
      return `<div class="chart-fill" style="width:${segWidthPct}%;background:${TIER_CHART_COLORS[tier]}" title="${escapeHtml(label)}: ${count}"></div>`;
    }).join("");
    return `
      <div class="chart-row">
        <div class="chart-label">${escapeHtml(d.group)}</div>
        <div class="chart-track-bg"><div class="chart-track" style="width:${trackWidthPct}%">${segments}</div></div>
        <div class="chart-value">${d.total}</div>
      </div>
    `;
  }).join("");

  const legend = [1, 2, 3].map((t) =>
    `<span class="chart-legend-item"><span class="chart-swatch" style="background:${TIER_CHART_COLORS[t]}"></span>${escapeHtml(TIER_META[t].label)}</span>`
  ).join("");

  return `
    <h4>By type, broken down by tier</h4>
    <div class="chart-block">${rows}<div class="chart-legend">${legend}</div></div>
  `;
}

function renderAuthorChart(list) {
  const counts = {};
  for (const s of list) counts[s.author] = (counts[s.author] || 0) + 1;
  const sorted = Object.entries(counts).sort((a, b) => b[1] - a[1]).slice(0, 12);
  if (sorted.length === 0) return "";
  const max = sorted[0][1];

  const rows = sorted.map(([author, count]) => {
    const pct = (count / max) * 100;
    return `
      <div class="chart-row">
        <div class="chart-label">${escapeHtml(author)}</div>
        <div class="chart-track-bg"><div class="chart-track" style="width:${pct}%"><div class="chart-fill" style="width:100%;background:var(--accent)"></div></div></div>
        <div class="chart-value">${count}</div>
      </div>
    `;
  }).join("");

  return `
    <h4>Top authors/orgs by entries listed</h4>
    <div class="chart-block">${rows}</div>
  `;
}

function renderTimelineChart(list) {
  const years = {};
  for (const s of list) {
    if (!s.repo_created_at) continue;
    const year = s.repo_created_at.slice(0, 4);
    years[year] = (years[year] || 0) + 1;
  }
  const sortedYears = Object.keys(years).sort();
  if (sortedYears.length === 0) return "";
  const max = Math.max(...Object.values(years), 1);

  const rows = sortedYears.map((year) => {
    const count = years[year];
    const pct = (count / max) * 100;
    return `
      <div class="chart-row">
        <div class="chart-label">${escapeHtml(year)}</div>
        <div class="chart-track-bg"><div class="chart-track" style="width:${pct}%"><div class="chart-fill" style="width:100%;background:var(--gold)"></div></div></div>
        <div class="chart-value">${count}</div>
      </div>
    `;
  }).join("");

  return `
    <h4>Repos by creation year</h4>
    <div class="chart-block">${rows}</div>
    <p class="chart-caveat">
      Only counts repos currently listed here, bucketed by their
      GitHub creation date - not a historical record (older repos
      that no longer exist or were never discovered aren't reflected).
    </p>
  `;
}

function renderStatsSection(list) {
  const totalSkills = list.filter((s) => s.type_group === "Skill").length;
  const totalPlugins = list.filter((s) => s.type_group === "Plugin").length;
  const totalTools = list.filter((s) => s.type_group === "Tool").length;
  const totalAuthors = new Set(list.map((s) => s.author)).size;

  const summary = `
    <div class="stat-summary-grid">
      <div class="stat-summary-cell"><div class="stat-summary-number">${list.length}</div><div class="stat-summary-label">Total listed</div></div>
      <div class="stat-summary-cell"><div class="stat-summary-number">${totalSkills}</div><div class="stat-summary-label">Skills</div></div>
      <div class="stat-summary-cell"><div class="stat-summary-number">${totalPlugins}</div><div class="stat-summary-label">Plugins</div></div>
      <div class="stat-summary-cell"><div class="stat-summary-number">${totalTools}</div><div class="stat-summary-label">Tools</div></div>
      <div class="stat-summary-cell"><div class="stat-summary-number">${totalAuthors}</div><div class="stat-summary-label">Authors/orgs</div></div>
    </div>
  `;

  statsContent.innerHTML =
    summary +
    renderTypeTierChart(list) +
    renderAuthorChart(list) +
    renderTimelineChart(list);
}

function applyFilters() {
  const query = searchInput.value.trim().toLowerCase();
  const showArchived = showArchivedToggle.checked;

  // facetsMatch: the Filters panel (filters.js)
  const filtered = skills.filter((s) =>
    matchesSearch(s, query) &&
    facetsMatch(s) &&
    (showArchived || !s.archived)
  );
  const sorted = sortSkills(filtered, sortOrder.value);

  render(sorted);
  renderNewSection(sorted);
  // Stats reflect exactly what's currently filtered/shown (including
  // the archived toggle) - not a fixed, independent total. Previously
  // computed once from the full unfiltered list on load, which could
  // show a different total than the "N skills listed" headline right
  // above it once someone applied any filter, including archived
  // ones staying counted even with "show archived" off.
  renderStatsSection(sorted);
  writeHash();
}

function renderStatsLine(meta, entryCount) {
  if (!meta) {
    statsLine.textContent = `${entryCount} skills & components listed.`;
    return;
  }
  const reviewed = meta.total_candidates_reviewed;
  const generated = formatDate(meta.generated_at);
  let text = `${entryCount} skills & components listed`;
  if (reviewed) text += ` (out of ${reviewed} repos reviewed)`;
  if (generated) text += ` · last checked ${generated}`;
  statsLine.textContent = text;

  // Queue visibility: how many newly-discovered repos haven't had
  // their first check yet, and how many got through this run - so
  // it's visible there's a backlog, and that it's shrinking over
  // time, not stuck. Only shown when there actually is a backlog
  // (e.g. right after a new discovery signal was added and found a
  // large batch of repos at once).
  const remaining = meta.new_candidates_remaining || 0;
  if (remaining > 0) {
    queueLine.textContent =
      `⛏️ ${remaining} newly-discovered repos still queued for their first check - we keep digging.`;
    queueLine.hidden = false;
  } else {
    queueLine.hidden = true;
  }
}

searchInput.addEventListener("input", applyFilters);
sortOrder.addEventListener("change", applyFilters);
siteLangSelect.addEventListener("change", () => {
  currentSiteLang = siteLangSelect.value;
  setSiteLanguage(currentSiteLang);
  applyFilters();
});

// cache: "no-store" plus a timestamp query param - belt and braces
// against a stale cached copy ever being served.
const cacheBust = `?t=${Date.now()}`;

Promise.all([
  fetch(`skills.json${cacheBust}`, { cache: "no-store" }).then((res) => {
    if (!res.ok) throw new Error(`skills.json: HTTP ${res.status}`);
    return res.json();
  }),
  fetch(`meta.json${cacheBust}`, { cache: "no-store" })
    .then((res) => (res.ok ? res.json() : null))
    .catch(() => null),
  // Optional: channel test results. Missing or broken never blocks the store.
  loadCompatResults(cacheBust),
  // Optional too: test reports from maintainers and users.
  loadReportsIndex(cacheBust),
])
  .then(([skillsData, metaData, compatData, reportsIndex]) => {
    skills = applyReports(applyCompatResults(skillsData, compatData), reportsIndex);
    initFacets(skills, applyFilters);
    populateSiteLangSelect(siteLangSelect);
    renderStatsLine(metaData, skills.length);
    applyFilters();
  })
  .catch((err) => {
    grid.innerHTML = "";
    emptyState.hidden = false;
    emptyState.textContent = `Could not load skills.json (${err.message}). Try refreshing the page.`;
  });
