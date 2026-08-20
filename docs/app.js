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
const authorFilter = document.getElementById("author-filter");
const tagFilter = document.getElementById("tag-filter");
const typeFilter = document.getElementById("type-filter");
const tierFilter = document.getElementById("tier-filter");
const languageFilter = document.getElementById("language-filter");
const sortOrder = document.getElementById("sort-order");
const showArchivedToggle = document.getElementById("show-archived");
const statsContent = document.getElementById("stats-content");

let skills = [];

function renderCard(skill) {
  const examples = asArray(skill.examples).slice(0, 3)
    .map((e) => `<li>"${escapeHtml(e)}"</li>`).join("");
  const tags = asArray(skill.tags)
    .map((t) => `<span class="tag">${escapeHtml(t)}</span>`).join("");
  const fallbackIcon = genericIconFor(skill);
  const icon = skill.icon || fallbackIcon;
  const version = skill.pypi_version ? `v${escapeHtml(skill.pypi_version)}` : "unreleased";
  const description = truncate(skill.description, MAX_DESCRIPTION_LENGTH);
  const stats = [];
  if (skill.stars) stats.push(`⭐ ${skill.stars}`);
  if (skill.forks) stats.push(`🍴 ${skill.forks}`);
  const statsLine = stats.length ? `<div class="stats">${stats.join(" · ")}</div>` : "";
  const detailUrl = `detail.html?id=${encodeURIComponent(skill.id)}`;

  return `
    <article class="card tier-${skill.tier}">
      <a class="card-link" href="${escapeHtml(detailUrl)}">
        <div class="card-head">
          <img src="${escapeHtml(icon)}" alt="" loading="lazy"
               onerror="this.onerror=null;this.src='${fallbackIcon}'">
          <div class="card-head-text">
            <h2>${escapeHtml(skill.name)}</h2>
            <div class="byline">by ${escapeHtml(skill.author)} · ${version}</div>
            ${statsLine}
            ${renderLanguageFlags(skill)}
          </div>
        </div>
        <div class="badges">${renderBadges(skill)}</div>
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
  if (order === "stars") {
    sorted.sort((a, b) => (b.stars || 0) - (a.stars || 0));
  } else if (order === "newest") {
    sorted.sort((a, b) => new Date(b.last_updated || 0) - new Date(a.last_updated || 0));
  } else {
    sorted.sort((a, b) => (a.name || "").localeCompare(b.name || ""));
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

function populateFilters(list) {
  const authors = [...new Set(list.map((s) => s.author))].sort((a, b) => a.localeCompare(b));

  for (const a of authors) {
    const opt = document.createElement("option");
    opt.value = a;
    opt.textContent = a;
    authorFilter.appendChild(opt);
  }

  // Tag filter: "our" curated categories first (the same grouping
  // the main grid uses - Daily, News, Other, ...), then every raw
  // tag value underneath - previously one long flat alphabetical
  // list where the handful of meaningful categories were buried
  // among hundreds of one-off raw tags (Actors, aes, agent, aiy,
  // ...). Category options are prefixed "cat:" so applyFilters can
  // tell them apart from raw "tag:" values sharing the same select.
  const categories = [...new Set(list.map((s) => s.category).filter(Boolean))]
    .sort((a, b) => {
      if (a === "Other") return 1;
      if (b === "Other") return -1;
      return a.localeCompare(b);
    });
  const rawTags = [...new Set(list.flatMap((s) => asArray(s.tags)))].sort((a, b) => a.localeCompare(b));

  if (categories.length > 0) {
    const optgroup = document.createElement("optgroup");
    optgroup.label = "Categories";
    for (const c of categories) {
      const opt = document.createElement("option");
      opt.value = `cat:${c}`;
      opt.textContent = c;
      optgroup.appendChild(opt);
    }
    tagFilter.appendChild(optgroup);
  }
  if (rawTags.length > 0) {
    const optgroup = document.createElement("optgroup");
    optgroup.label = "All Tags";
    for (const t of rawTags) {
      const opt = document.createElement("option");
      opt.value = `tag:${t}`;
      opt.textContent = t;
      optgroup.appendChild(opt);
    }
    tagFilter.appendChild(optgroup);
  }

  const pluginTypes = new Set();
  let hasSkill = false;
  let hasTool = false;
  for (const s of list) {
    if (!s.component_type) continue;
    if (s.type_group === "Skill") hasSkill = true;
    else if (s.type_group === "Tool") hasTool = true;
    else pluginTypes.add(s.component_type);
  }

  if (hasSkill) {
    const opt = document.createElement("option");
    opt.value = "Skill";
    opt.textContent = "Skill";
    typeFilter.appendChild(opt);
  }
  if (pluginTypes.size > 0) {
    // "All Plugins" as its own selectable option (not just an
    // optgroup label, which HTML can't make clickable on its own),
    // matching by type_group so any plugin type counts - separate
    // from the specific nested types below it.
    const allPluginsOpt = document.createElement("option");
    allPluginsOpt.value = "__all_plugins__";
    allPluginsOpt.textContent = "All Plugins";
    typeFilter.appendChild(allPluginsOpt);

    const optgroup = document.createElement("optgroup");
    optgroup.label = "Plugins";
    for (const t of [...pluginTypes].sort((a, b) => a.localeCompare(b))) {
      const opt = document.createElement("option");
      opt.value = t;
      opt.textContent = t;
      optgroup.appendChild(opt);
    }
    typeFilter.appendChild(optgroup);
  }
  if (hasTool) {
    const opt = document.createElement("option");
    opt.value = "Tool";
    opt.textContent = "Tool";
    typeFilter.appendChild(opt);
  }

  // Tier filter: matches the site's own badge labels, not raw tier
  // numbers, so the dropdown reads the same as what's on each card.
  const TIER_OPTIONS = [
    { value: "1", label: "Looks Complete" },
    { value: "2", label: "Incomplete" },
    { value: "3", label: "Inferred, Unconfirmed" },
  ];
  const presentTiers = new Set(list.map((s) => String(s.tier)));
  for (const { value, label } of TIER_OPTIONS) {
    if (!presentTiers.has(value)) continue;
    const opt = document.createElement("option");
    opt.value = value;
    opt.textContent = label;
    tierFilter.appendChild(opt);
  }

  // Language filter: "if someone speaks Spanish, they'd want to see
  // skills listed with Spanish support" - populated from every
  // distinct locale code actually present across skills' languages
  // arrays, shown with its flag for quick scanning.
  const languages = [...new Set(list.flatMap((s) => asArray(s.languages)))].sort((a, b) => a.localeCompare(b));
  for (const l of languages) {
    const opt = document.createElement("option");
    opt.value = l;
    opt.textContent = `${languageFlag(l)} ${l}`;
    languageFilter.appendChild(opt);
  }
}

function matchesSearch(skill, query) {
  if (!query) return true;
  const haystack = [
    skill.name, skill.description, skill.author,
    ...asArray(skill.tags), ...asArray(skill.examples),
  ].join(" ").toLowerCase();
  return haystack.includes(query);
}

function matchesTagFilter(skill, tagValue) {
  if (!tagValue) return true;
  if (tagValue.startsWith("cat:")) {
    return skill.category === tagValue.slice(4);
  }
  if (tagValue.startsWith("tag:")) {
    return asArray(skill.tags).includes(tagValue.slice(4));
  }
  return true;
}

function matchesTypeFilter(skill, typeValue) {
  if (!typeValue) return true;
  if (typeValue === "__all_plugins__") return skill.type_group === "Plugin";
  return skill.component_type === typeValue;
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
  const author = authorFilter.value;
  const tag = tagFilter.value;
  const type = typeFilter.value;
  const tier = tierFilter.value;
  const language = languageFilter.value;
  const showArchived = showArchivedToggle.checked;

  const filtered = skills.filter((s) =>
    matchesSearch(s, query) &&
    (!author || s.author === author) &&
    matchesTagFilter(s, tag) &&
    matchesTypeFilter(s, type) &&
    (!tier || String(s.tier) === tier) &&
    (!language || asArray(s.languages).includes(language)) &&
    (showArchived || !s.archived)
  );
  const sorted = sortSkills(filtered, sortOrder.value);

  render(sorted);
  renderNewSection(sorted);
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
authorFilter.addEventListener("change", applyFilters);
tagFilter.addEventListener("change", applyFilters);
typeFilter.addEventListener("change", applyFilters);
tierFilter.addEventListener("change", applyFilters);
languageFilter.addEventListener("change", applyFilters);
sortOrder.addEventListener("change", applyFilters);
showArchivedToggle.addEventListener("change", applyFilters);

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
])
  .then(([skillsData, metaData]) => {
    skills = skillsData;
    populateFilters(skills);
    renderStatsLine(metaData, skills.length);
    renderStatsSection(skills);
    applyFilters();
  })
  .catch((err) => {
    grid.innerHTML = "";
    emptyState.hidden = false;
    emptyState.textContent = `Could not load skills.json (${err.message}). Try refreshing the page.`;
  });
