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
const languageFilter = document.getElementById("language-filter");
const sortOrder = document.getElementById("sort-order");

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

function applyFilters() {
  const query = searchInput.value.trim().toLowerCase();
  const author = authorFilter.value;
  const tag = tagFilter.value;
  const type = typeFilter.value;
  const language = languageFilter.value;

  const filtered = skills.filter((s) =>
    matchesSearch(s, query) &&
    (!author || s.author === author) &&
    matchesTagFilter(s, tag) &&
    (!type || s.component_type === type) &&
    (!language || asArray(s.languages).includes(language))
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
    const doneThisRun = meta.new_candidates_processed_this_run || 0;
    queueLine.textContent =
      `⛏️ ${remaining} newly-discovered repos still queued for their first check ` +
      `(${doneThisRun} processed this run) - shrinks a little every run.`;
    queueLine.hidden = false;
  } else {
    queueLine.hidden = true;
  }
}

searchInput.addEventListener("input", applyFilters);
authorFilter.addEventListener("change", applyFilters);
tagFilter.addEventListener("change", applyFilters);
typeFilter.addEventListener("change", applyFilters);
languageFilter.addEventListener("change", applyFilters);
sortOrder.addEventListener("change", applyFilters);

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
    applyFilters();
  })
  .catch((err) => {
    grid.innerHTML = "";
    emptyState.hidden = false;
    emptyState.textContent = `Could not load skills.json (${err.message}). Try refreshing the page.`;
  });
