const grid = document.getElementById("grid");
const newSection = document.getElementById("new-section");
const newGrid = document.getElementById("new-grid");
const emptyState = document.getElementById("empty-state");
const searchInput = document.getElementById("search");
const authorFilter = document.getElementById("author-filter");
const tagFilter = document.getElementById("tag-filter");

let skills = [];

const STORE_BADGE_SVG = `<svg viewBox="0 0 20 20" fill="currentColor" aria-hidden="true">
  <path fill-rule="evenodd" d="M16.7 5.3a1 1 0 0 1 0 1.4l-7 7a1 1 0 0 1-1.4 0l-3.5-3.5a1 1 0 1 1 1.4-1.4l2.8 2.8 6.3-6.3a1 1 0 0 1 1.4 0z" clip-rule="evenodd"/>
</svg>`;

const CONNECTIVITY_META = {
  offline: { label: "Offline", cls: "badge-offline" },
  hybrid: { label: "Hybrid", cls: "badge-hybrid" },
  online: { label: "Online", cls: "badge-online" },
};

const TIER_META = {
  1: { label: "Verified", cls: "badge-verified" },
  2: { label: "Partial", cls: "badge-partial" },
  3: { label: "Unverified", cls: "badge-unverified" },
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

function renderBadges(skill) {
  const badges = [];

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
  return badges.join("");
}

function renderCard(skill) {
  const examples = (skill.examples || []).slice(0, 3)
    .map((e) => `<li>"${escapeHtml(e)}"</li>`).join("");
  const tags = (skill.tags || [])
    .map((t) => `<span class="tag">${escapeHtml(t)}</span>`).join("");
  const icon = skill.icon || "";
  const version = skill.pypi_version ? `v${escapeHtml(skill.pypi_version)}` : "unreleased";

  return `
    <article class="card tier-${skill.tier}">
      <div class="card-head">
        <img src="${escapeHtml(icon)}" alt="" loading="lazy"
             onerror="this.style.visibility='hidden'">
        <div class="card-head-text">
          <h2>${escapeHtml(skill.name)}</h2>
          <div class="byline">by ${escapeHtml(skill.author)} · ${version}</div>
        </div>
      </div>
      <div class="badges">${renderBadges(skill)}</div>
      <p class="description">${escapeHtml(skill.description)}</p>
      <ul class="examples">${examples}</ul>
      <div class="tags">${tags}</div>
      <div class="links">
        <a href="${escapeHtml(skill.source)}" target="_blank" rel="noopener">GitHub</a>
        ${skill.package_name ? `<a href="https://pypi.org/project/${escapeHtml(skill.package_name)}/" target="_blank" rel="noopener">PyPI</a>` : ""}
      </div>
    </article>
  `;
}

function groupByCategory(list) {
  const groups = new Map();
  for (const skill of list) {
    const cat = skill.category || "Other";
    if (!groups.has(cat)) groups.set(cat, []);
    groups.get(cat).push(skill);
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

  const filtered = skills.filter((s) =>
    matchesSearch(s, query) &&
    (!author || s.author === author) &&
    (!tag || (s.tags || []).includes(tag))
  );

  render(filtered);
  // The "new" section always reflects the current filter set too,
  // so filtering by author/tag still shows their recent additions.
  renderNewSection(filtered);
}

searchInput.addEventListener("input", applyFilters);
authorFilter.addEventListener("change", applyFilters);
tagFilter.addEventListener("change", applyFilters);

fetch("skills.json")
  .then((res) => res.json())
  .then((data) => {
    skills = data;
    populateFilters(skills);
    render(skills);
    renderNewSection(skills);
  })
  .catch(() => {
    grid.innerHTML = "";
    emptyState.hidden = false;
    emptyState.textContent = "Could not load skills.json.";
  });
