// Index page filters: one "Filters" panel with a group of toggle chips per
// facet (type, status, OVOS tests, category, language, tag, author).
// Several values can be picked in each group: within a group any of them
// matches, between groups all must match. What is picked shows as
// removable chips under the search box, and lives in the URL hash so a
// filtered view can be shared or bookmarked.
// Needs shared.js (escapeHtml, asArray, languageFlag, matchesCompatFilter).

const TIER_LABELS = { 1: "Looks Complete", 2: "Incomplete", 3: "Inferred, Unconfirmed" };

const COMPAT_OPTIONS = [
  ["tested", "Tested on OVOS"],
  ["loads:testing", "✓ Works on testing"],
  ["loads:alpha", "✓ Works on alpha"],
  ["loads:stable", "✓ Works on stable"],
  ["loads:installer", "✓ Works on testing and alpha"],
  ["routes:testing", "✓ Routes on testing"],
  ["routes:alpha", "✓ Routes on alpha"],
  ["routes:stable", "✓ Routes on stable"],
  ["fails:testing", "✗ Fails on testing"],
  ["fails:alpha", "✗ Fails on alpha"],
  ["fails:stable", "✗ Fails on stable"],
];

// id: URL key; label: group title; test(skill, value); options(list) -> [{value, label, html?}]
// limit: how many chips show before "Show all"; searchable: a small box to narrow the chips.
const FACETS = [
  {
    id: "type", label: "Type",
    options(list) {
      const out = [];
      const has = (g) => list.some((s) => s.type_group === g);
      if (has("Skill")) out.push({ value: "Skill", label: "Skill" });
      if (has("Tool")) out.push({ value: "Tool", label: "Tool" });
      if (has("Infrastructure")) out.push({ value: "Infrastructure", label: "Infrastructure" });
      const pluginTypes = [...new Set(list.filter((s) => s.type_group === "Plugin" && s.component_type)
        .map((s) => s.component_type))].sort((a, b) => a.localeCompare(b));
      if (pluginTypes.length) {
        out.push({ value: "__all_plugins__", label: "All plugins" });
        for (const t of pluginTypes) out.push({ value: t, label: t });
      }
      return out;
    },
    test(s, v) {
      if (v === "__all_plugins__") return s.type_group === "Plugin";
      if (["Skill", "Tool", "Infrastructure"].includes(v)) return s.type_group === v || s.component_type === v;
      return s.component_type === v;
    },
    limit: 12,
  },
  {
    id: "compat", label: "Tested on OVOS",
    help: "testing is what the OVOS installer installs by default.",
    options: () => COMPAT_OPTIONS.map(([value, label]) => ({ value, label })),
    test: (s, v) => matchesCompatFilter(s, v),
    limit: 20,
  },
  {
    id: "tier", label: "Status",
    options: (list) => [1, 2, 3].filter((t) => list.some((s) => String(s.tier) === String(t)))
      .map((t) => ({ value: String(t), label: TIER_LABELS[t] })),
    test: (s, v) => String(s.tier) === v,
  },
  {
    id: "category", label: "Category",
    options: (list) => countValues(list, (s) => (s.category ? [s.category] : []))
      .sort((a, b) => (a.value === "Other") - (b.value === "Other") || a.value.localeCompare(b.value)),
    test: (s, v) => s.category === v,
    limit: 30,
  },
  {
    id: "language", label: "Language",
    options: (list) => countValues(list, (s) => asArray(s.languages))
      .map((o) => ({ ...o, html: `${languageFlag(o.value)} ${escapeHtml(o.value)}` })),
    test: (s, v) => asArray(s.languages).includes(v),
    limit: 16, searchable: true,
  },
  {
    id: "tag", label: "Tag",
    options: (list) => countValues(list, (s) => asArray(s.tags)),
    test: (s, v) => asArray(s.tags).includes(v),
    limit: 24, searchable: true,
  },
  {
    id: "author", label: "Author",
    options: (list) => countValues(list, (s) => (s.author ? [s.author] : [])),
    test: (s, v) => s.author === v,
    limit: 16, searchable: true,
  },
];

// most used first, then A-Z
function countValues(list, valuesOf) {
  const counts = new Map();
  for (const s of list) for (const v of new Set(valuesOf(s))) counts.set(v, (counts.get(v) || 0) + 1);
  return [...counts].map(([value, n]) => ({ value, label: value, n }))
    .sort((a, b) => b.n - a.n || a.value.localeCompare(b.value));
}

const facetState = Object.fromEntries(FACETS.map((f) => [f.id, new Set()]));
const facetOptions = {};
const facetExpanded = {};
const facetQuery = {};
let facetsOnChange = () => {};

function facetsMatch(skill) {
  return FACETS.every((f) => {
    const picked = facetState[f.id];
    return picked.size === 0 || [...picked].some((v) => f.test(skill, v));
  });
}

function facetLabel(facet, value) {
  const o = (facetOptions[facet.id] || []).find((x) => x.value === value);
  return o ? (o.html || escapeHtml(o.label)) : escapeHtml(value);
}

function pickedCount() {
  return FACETS.reduce((n, f) => n + facetState[f.id].size, 0);
}

function renderFacet(facet) {
  const all = facetOptions[facet.id] || [];
  if (!all.length) return "";
  const picked = facetState[facet.id];
  const q = (facetQuery[facet.id] || "").toLowerCase();
  let shown = q ? all.filter((o) => o.label.toLowerCase().includes(q)) : all;
  const limit = facet.limit || 50;
  const more = !q && !facetExpanded[facet.id] && shown.length > limit ? shown.length - limit : 0;
  if (more) {
    // picked values always stay visible
    shown = shown.filter((o, i) => i < limit || picked.has(o.value));
  }
  const chips = shown.map((o) => {
    const on = picked.has(o.value);
    const count = o.n ? ` <span class="chip-count">${o.n}</span>` : "";
    return `<button type="button" class="chip${on ? " chip-on" : ""}" aria-pressed="${on}"
      data-facet="${facet.id}" data-value="${escapeHtml(o.value)}">${o.html || escapeHtml(o.label)}${count}</button>`;
  }).join("");
  const search = facet.searchable && all.length > limit
    ? `<input type="search" class="facet-search" data-facet="${facet.id}" placeholder="Find ${/^[aeiou]/i.test(facet.label) ? "an" : "a"} ${facet.label.toLowerCase()}…"
         value="${escapeHtml(facetQuery[facet.id] || "")}" aria-label="Find ${/^[aeiou]/i.test(facet.label) ? "an" : "a"} ${facet.label.toLowerCase()}">` : "";
  const toggle = more
    ? `<button type="button" class="link-button facet-more" data-facet="${facet.id}">Show all ${all.length}</button>`
    : (facetExpanded[facet.id] && !q && all.length > limit
      ? `<button type="button" class="link-button facet-more" data-facet="${facet.id}">Show fewer</button>` : "");
  const help = facet.help ? `<span class="facet-help">${escapeHtml(facet.help)}</span>` : "";
  return `<section class="facet" data-facet-section="${facet.id}">
    <div class="facet-head"><h3>${escapeHtml(facet.label)}</h3>${help}${search}</div>
    <div class="facet-chips">${chips || '<span class="facet-help">No match</span>'}${toggle}</div>
  </section>`;
}

function renderFacets() {
  const box = document.getElementById("facets");
  const focused = document.activeElement && document.activeElement.classList.contains("facet-search")
    ? document.activeElement.dataset.facet : null;
  box.innerHTML = FACETS.map(renderFacet).join("");
  if (focused) {
    const input = box.querySelector(`.facet-search[data-facet="${focused}"]`);
    if (input) { input.focus(); input.setSelectionRange(input.value.length, input.value.length); }
  }
  renderActiveFilters();
}

function renderActiveFilters() {
  const box = document.getElementById("active-filters");
  const chips = [];
  for (const f of FACETS) {
    for (const v of facetState[f.id]) {
      chips.push(`<button type="button" class="chip chip-on chip-remove" data-facet="${f.id}" data-value="${escapeHtml(v)}"
        title="Remove this filter"><span class="chip-facet">${escapeHtml(f.label)}:</span> ${facetLabel(f, v)} <span aria-hidden="true">×</span></button>`);
    }
  }
  const archived = document.getElementById("show-archived");
  if (archived && archived.checked) {
    chips.push(`<button type="button" class="chip chip-on chip-remove" data-archived="1" title="Remove this filter">Archived shown <span aria-hidden="true">×</span></button>`);
  }
  box.hidden = chips.length === 0;
  box.innerHTML = chips.join("") + (chips.length > 1 ? '<button type="button" class="link-button" data-clear="1">Clear all</button>' : "");
  const count = document.getElementById("filters-count");
  const n = pickedCount();
  count.hidden = n === 0;
  count.textContent = n;
}

function toggleFacet(id, value) {
  const set = facetState[id];
  if (set.has(value)) set.delete(value); else set.add(value);
  changed();
}

function clearFacets() {
  for (const f of FACETS) facetState[f.id].clear();
  const archived = document.getElementById("show-archived");
  if (archived) archived.checked = false;
  changed();
}

function changed() {
  renderFacets();
  writeHash();
  facetsOnChange();
}

// ---- URL hash: #type=Skill,Tool&tag=weather&q=timer&sort=stars&archived=1
function writeHash() {
  const params = new URLSearchParams();
  const q = document.getElementById("search").value.trim();
  if (q) params.set("q", q);
  for (const f of FACETS) {
    if (facetState[f.id].size) params.set(f.id, [...facetState[f.id]].join(","));
  }
  const sort = document.getElementById("sort-order").value;
  if (sort && sort !== "recommended") params.set("sort", sort);
  if (document.getElementById("show-archived").checked) params.set("archived", "1");
  const hash = params.toString();
  history.replaceState(null, "", hash ? `#${hash}` : window.location.pathname + window.location.search);
}

function readHash() {
  const params = new URLSearchParams(window.location.hash.slice(1));
  for (const f of FACETS) {
    facetState[f.id].clear();
    const raw = params.get(f.id);
    if (raw) for (const v of raw.split(",")) if (v) facetState[f.id].add(v);
  }
  if (params.get("q")) document.getElementById("search").value = params.get("q");
  if (params.get("sort")) document.getElementById("sort-order").value = params.get("sort");
  document.getElementById("show-archived").checked = params.get("archived") === "1";
}

function setPanelOpen(open) {
  const panel = document.getElementById("filters-panel");
  const button = document.getElementById("filters-toggle");
  panel.hidden = !open;
  button.setAttribute("aria-expanded", String(open));
}

function initFacets(list, onChange) {
  facetsOnChange = onChange;
  for (const f of FACETS) {
    // every chip says how many entries it matches; chips matching none are left out
    facetOptions[f.id] = f.options(list)
      .map((o) => (o.n ? o : { ...o, n: list.filter((s) => f.test(s, o.value)).length }))
      .filter((o) => o.n > 0);
  }
  readHash();
  renderFacets();

  document.getElementById("filters-toggle").addEventListener("click", () =>
    setPanelOpen(document.getElementById("filters-panel").hidden));
  document.getElementById("filters-done").addEventListener("click", () => setPanelOpen(false));
  document.getElementById("filters-clear").addEventListener("click", clearFacets);
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && !document.getElementById("filters-panel").hidden) setPanelOpen(false);
  });

  const onChip = (e) => {
    const chip = e.target.closest("button");
    if (!chip) return;
    if (chip.dataset.clear) return clearFacets();
    if (chip.dataset.archived) {
      document.getElementById("show-archived").checked = false;
      return changed();
    }
    if (chip.classList.contains("facet-more")) {
      facetExpanded[chip.dataset.facet] = !facetExpanded[chip.dataset.facet];
      return renderFacets();
    }
    if (chip.dataset.facet) toggleFacet(chip.dataset.facet, chip.dataset.value);
  };
  document.getElementById("facets").addEventListener("click", onChip);
  document.getElementById("active-filters").addEventListener("click", onChip);
  document.getElementById("facets").addEventListener("input", (e) => {
    if (!e.target.classList.contains("facet-search")) return;
    facetQuery[e.target.dataset.facet] = e.target.value;
    renderFacets();
  });
  document.getElementById("show-archived").addEventListener("change", changed);
  window.addEventListener("hashchange", () => { readHash(); renderFacets(); facetsOnChange(); });
}
