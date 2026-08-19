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

// A plain gray placeholder (no external asset) shown when a skill
// has no icon, or its icon URL fails to load - as a data: URI so it
// never triggers a second failed network request.
const GENERIC_ICON =
  "data:image/svg+xml;utf8," +
  encodeURIComponent(
    `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 44 44">
       <rect width="44" height="44" rx="10" fill="#e2e5ea"/>
       <path d="M22 12a10 10 0 100 20 10 10 0 000-20zm0 3a2.5 2.5 0 110 5 2.5 2.5 0 010-5zm3.5 12h-7v-1.2c0-1.9 2.3-3.3 3.5-3.3s3.5 1.4 3.5 3.3z" fill="#9aa0ab"/>
     </svg>`
  );

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
  const examples = (skill.examples || []).slice(0, 3)
    .map((e) => `<li>"${escapeHtml(e)}"</li>`).join("");
  const tags = (skill.tags || [])
    .map((t) => `<span class="tag">${escapeHtml(t)}</span>`).join("");
  const icon = skill.icon || GENERIC_ICON;
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
             onerror="this.onerror=null;this.src='${GENERIC_ICON}'">
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

function renderNewSection(list) {
  const recent = list.filter((s) => s.is_new);
  if (recent.length === 0) {
    newSection.hidden = true;
    return;
  }
  newSection.hidden = false;
  newGrid.innerHTML = recent.map(renderCard).join("");
}

function populateFilters(list) {
  const authors = [...new Set(list.map((s) => s.author))].sort((a, b) => a.localeCompare(b));
  const tags = [...new Set(list.flatMap((s) => s.tags || []))].sort((a, b) => a.localeCompare(b));
  const types = [...new Set(list.map((s) => s.component_type).filter(Boolean))].sort((a, b) => a.localeCompare(b));

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
  for (const t of types) {
    const opt = document.createElement("option");
    opt.value = t;
    opt.textContent = t;
    typeFilter.appendChild(opt);
  }
}

function matchesSearch(skill, query) {
  if (!query) return true;
  const haystack = [
    skill.name, skill.description, skill.author,
    ...(skill.tags || []), ...(skill.examples || []),
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
    (!tag || (s.tags || []).includes(tag)) &&
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
