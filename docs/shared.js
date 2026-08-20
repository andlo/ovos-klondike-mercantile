// Shared between index.html (app.js) and detail.html (detail.js) -
// constants and pure rendering helpers with no dependency on either
// page's specific DOM structure.

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
const GENERIC_ICON = GENERIC_ICON_PLUGIN; // ultimate fallback

function genericIconFor(skill) {
  if (skill.type_group === "Skill") return GENERIC_ICON_SKILL;
  if (skill.type_group === "Tool") return GENERIC_ICON_TOOL;
  return GENERIC_ICON_PLUGIN;
}

const MAX_DESCRIPTION_LENGTH = 160;

// Connectivity labels deliberately avoid the word "Offline" alone -
// on its own it reads as "the skill is unavailable" rather than
// "works without internet". "Online" alone has the same problem in
// reverse, so it's paired with "Needs Internet" instead.
const CONNECTIVITY_META = {
  offline: { label: "Works Offline", cls: "badge-offline" },
  hybrid: { label: "Offline + Online", cls: "badge-hybrid" },
  online: { label: "Needs Internet", cls: "badge-online" },
};

// These intentionally do NOT say "Verified" - this system checks
// that the expected PIECES are present, not that the skill actually
// works. Real verification would mean running `pip install` and
// importing it - a distinct, larger feature this labeling doesn't
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

// Defense in depth: the generator normalizes tags/examples to always
// be arrays (see generate_klondike_data.py's normalize_tags, added
// after a real skill.json declared "tags" as a plain string, which
// crashed every .map() call on it). Kept here too in case a future
// data source has a shape this hasn't anticipated.
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
  if (skill.archived) {
    badges.push(`<span class="badge badge-warn">Archived</span>`);
  }
  return badges.join("");
}

function formatDate(iso) {
  if (!iso) return null;
  return new Date(iso).toLocaleDateString(undefined, {
    year: "numeric", month: "long", day: "numeric",
  });
}

// Computes a country flag emoji directly from a 2-letter region
// code via Unicode "regional indicator symbol" math - no lookup
// table needed. E.g. flagEmoji("us") -> 🇺🇸, flagEmoji("dk") -> 🇩🇰.
// Falls back to null for anything that isn't a clean 2-letter code
// (a handful of locale codes are language-only, with no region).
function flagEmoji(regionCode) {
  if (!regionCode || regionCode.length !== 2) return null;
  const upper = regionCode.toUpperCase();
  if (!/^[A-Z]{2}$/.test(upper)) return null;
  return String.fromCodePoint(
    ...[...upper].map((c) => 127397 + c.charCodeAt(0))
  );
}

// "en-us" -> flag for "us"; "da-dk" -> flag for "dk"; a bare
// language code with no region ("en") falls back to just the code
// itself, since there's no single flag for a language alone.
function languageFlag(localeCode) {
  const parts = localeCode.split("-");
  const region = parts.length > 1 ? parts[parts.length - 1] : null;
  const flag = region ? flagEmoji(region) : null;
  return flag || localeCode;
}

function renderLanguageFlags(skill) {
  const languages = asArray(skill.languages);
  if (languages.length === 0) return "";
  const flags = languages.map((l) =>
    `<span class="lang-flag" title="${escapeHtml(l)}">${languageFlag(l)}</span>`
  ).join("");
  return `<div class="lang-flags">${flags}</div>`;
}
