const grid = document.getElementById("grid");
const newSection = document.getElementById("new-section");
const newGrid = document.getElementById("new-grid");
const emptyState = document.getElementById("empty-state");
const statsLine = document.getElementById("stats-line");
const searchInput = document.getElementById("search");
const authorFilter = document.getElementById("author-filter");
const tagFilter = document.getElementById("tag-filter");
const typeFilter = document.getElementById("type-filter");
const sortOrder = document.getElementById("sort-order");

let skills = [];

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
// Kept as the ultimate fallback (unknown/missing type_group).
const GENERIC_ICON = GENERIC_ICON_PLUGIN;

function genericIconFor(skill) {
  if (skill.type_group === "Skill") return GENERIC_ICON_SKILL;
  if (skill.type_group === "Tool") return GENERIC_ICON_TOOL;
  return GENERIC_ICON_PLUGIN;
}

const MAX_DESCRIPTION_LENGTH = 160;

// Connectivity labels deliberately avoid the word "Offline" alone -
// on its own it reads as "the skill is unavailable" rather than
// "works without internet" (requested after exactly that confusion
// came up). "Online" alone has the same problem in reverse, so it's
// paired with "Needs Internet" instead.
const CONNECTIVITY_META = {
  offline: { label: "Works Offline", cls: "badge-offline" },
  hybrid: { label: "Offline + Online", cls: "badge-hybrid" },
  online: { label: "Needs Internet", cls: "badge-online" },
};

// These intentionally do NOT say "Verified" - this system checks
// that the expected PIECES are present (a skill.json, a PyPI
// release, a GitHub release), not that the skill actually works.
// Real verification would mean running `pip install` and importing
// it - a real, larger feature this labeling deliberately doesn't
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

// Defense in depth: the generator now normalizes tags/examples to
// always be arrays (see generate_klondike_data.py's normalize_tags,
// added after ovos-skill-laugh/ovos-skill-randomness's own
// skill.json turned out to declare "tags" as a plain string, which
// crashed every .map() call on it - `value || []` alone doesn't
// catch a truthy non-array value like a string). Kept here too in
// case a future data source has a shape this hasn't anticipated.
function asArray(value) {
  return Array.isArray(value) ? value : [];
}

function pipelineLabel(pipelinePackage) {
  return pipelinePackage
    .replace(/^ovos-/, "")
    .replace(/-plugin$/, "")
    .split("-")
    .map((w) => w.charAt(0).toUpperCase() + w.slice(1))
    .join(" ") + " Pipeline";
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
  if (!skill.on_pypi) {
    badges.push(`<span class="badge badge-warn">Not on PyPI</span>`);
  }
  if (!skill.has_release) {
    badges.push(`<span class="badge badge-warn">No release</span>`);
  }
  if (!skill.license) {
    badges.push(`<span class="badge badge-warn">No license</span>`);
  }
  return badges.join("");
}

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

  return `
    <article class="card tier-${skill.tier}">
      <div class="card-head">
        <img src="${escapeHtml(icon)}" alt="" loading="lazy"
             onerror="this.onerror=null;this.src='${fallbackIcon}'">
        <div class="card-head-text">
          <h2>${escapeHtml(skill.name)}</h2>
          <div class="byline">by ${escapeHtml(skill.author)} · ${version}</div>
          ${statsLine}
        </div>
      </div>
      <div class="badges">${renderBadges(skill)}</div>
      <p class="description">${escapeHtml(description)}</p>
      <ul class="examples">${examples}</ul>
      <div class="tags">${tags}</div>
      <div class="links">
        <a href="${escapeHtml(skill.source)}" target="_blank" rel="noopener">GitHub</a>
        ${skill.package_name ? `<a href="https://pypi.org/project/${escapeHtml(skill.package_name)}/" target="_blank" rel="noopener">PyPI</a>` : ""}
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
  // "Other" last, everything else alphabetical
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
  // Two DIFFERENT things, deliberately not merged: a repo that's
  // genuinely young (is_new_repo, from its GitHub creation date) is
  // a more noteworthy kind of "new" than an existing, long-running
  // project simply shipping a fresh release (is_recently_updated).
  // A repo matching both only shows once, under "New repos".
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
    // Capped, not an unbounded list - with 269+ entries a "new"
    // section can itself get large enough to need this (found while
    // testing: many repos in the same weekly batch legitimately
    // qualify at once).
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
  const tags = [...new Set(list.flatMap((s) => asArray(s.tags)))].sort((a, b) => a.localeCompare(b));

  for (const a of authors) {
    const opt = document.createElement("option");
    opt.value = a;
    opt.textContent = a;
    authorFilter.appendChild(opt);
  }
  for (const t of tags) {
    const opt = document.createElement("option");
    opt.value = t;
    opt.textContent = t;
    tagFilter.appendChild(opt);
  }

  // Type filter: hierarchical (Skill / Plugins / Tool) instead of
  // one long flat list, which got hard to scan once component-type
  // detection started covering a dozen+ specific plugin categories
  // (OCP, TTS, STT, Persona, Pipeline, ...). Skill and Tool are
  // single, standalone options; every specific plugin type nests
  // under one "Plugins" optgroup.
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
}

function matchesSearch(skill, query) {
  if (!query) return true;
  const haystack = [
    skill.name, skill.description, skill.author,
    ...asArray(skill.tags), ...asArray(skill.examples),
  ].join(" ").toLowerCase();
  return haystack.includes(query);
}

function applyFilters() {
  const query = searchInput.value.trim().toLowerCase();
  const author = authorFilter.value;
  const tag = tagFilter.value;
  const type = typeFilter.value;

  const filtered = skills.filter((s) =>
    matchesSearch(s, query) &&
    (!author || s.author === author) &&
    (!tag || asArray(s.tags).includes(tag)) &&
    (!type || s.component_type === type)
  );
  const sorted = sortSkills(filtered, sortOrder.value);

  render(sorted);
  // The "new" section always reflects the current filter set too,
  // so filtering by author/tag/type still shows their recent additions.
  renderNewSection(sorted);
}

function renderStatsLine(meta, entryCount) {
  if (!meta) {
    statsLine.textContent = `${entryCount} skills & components listed.`;
    return;
  }
  const reviewed = meta.total_candidates_reviewed;
  const generated = meta.generated_at
    ? new Date(meta.generated_at).toLocaleDateString(undefined, {
        year: "numeric", month: "long", day: "numeric",
      })
    : null;
  let text = `${entryCount} skills & components listed`;
  if (reviewed) text += ` (out of ${reviewed} repos reviewed)`;
  if (generated) text += ` · last checked ${generated}`;
  statsLine.textContent = text;
}

searchInput.addEventListener("input", applyFilters);
authorFilter.addEventListener("change", applyFilters);
tagFilter.addEventListener("change", applyFilters);
typeFilter.addEventListener("change", applyFilters);
sortOrder.addEventListener("change", applyFilters);

// cache: "no-store" plus a timestamp query param - belt and braces
// against a stale cached copy ever being served, after exactly that
// was suspected as the cause of a "could not load" / stale-filter
// report from a real user session.
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
