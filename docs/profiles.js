// Test overview by install profile (profiles.html): Default, + Extra and
// + Klondike, per channel. Reads docs/compat/profile-report.json, written
// by scripts/compat/profile_report.py from compat/results.json after every
// test run, and docs/skills.json only for display names.
(function () {
  const tabsEl = document.querySelector("[data-profile-tabs]");
  const metaEl = document.querySelector("[data-profile-meta]");
  const summaryEl = document.querySelector("[data-profile-summary]");
  const sectionsEl = document.querySelector("[data-profile-sections]");
  const problemsEl = document.querySelector("[data-profile-problems]");
  const filterTextEl = document.querySelector("[data-profile-filter-text]");
  if (!sectionsEl) return;

  // testing first: what the OVOS installer installs by default.
  const TAB_ORDER = ["testing", "alpha", "stable"];
  // feed.label() already starts pass/warn/fail labels with ✓ or ✗.
  const STATE_MARK = { unsupported: "–", untested: "·", not_in_store: "∅" };
  const PROFILE_TITLE = { default: "Default", extra: "+ Extra", klondike: "+ Klondike" };
  let report = null;
  let names = {};
  let channel = null;

  function readHash() {
    const h = decodeURIComponent(location.hash.slice(1)).split("-")[0];
    return report && (h === "compare" || report.channels[h]) ? h : null;
  }

  function pct(n, d) {
    return d ? Math.round((100 * n) / d) : 0;
  }

  function isProblem(e) {
    return e.state !== "pass" || (e.klondike && e.klondike.hit < e.klondike.counted);
  }

  function nameCell(e) {
    const label = (e.store_id && names[e.store_id]) || e.runtime_id;
    const main = e.store_id
      ? `<a href="detail.html?id=${encodeURIComponent(e.store_id)}">${escapeHtml(label)}</a>`
      : escapeHtml(label);
    const sub = label !== e.runtime_id ? `<div class="profile-sub"><code>${escapeHtml(e.runtime_id)}</code></div>` : "";
    const note = e.note ? `<div class="profile-sub">${escapeHtml(e.note)}</div>` : "";
    return `${main}${sub}${note}`;
  }

  function resultCell(e) {
    const tip = [e.label, e.level !== null && e.level !== undefined ? COMPAT_LEVEL_TEXT[e.level] : "",
      e.tested_at ? `tested ${formatDate(e.tested_at)}` : ""].filter(Boolean).join(" · ");
    const cls = e.state === "not_in_store" ? "untested" : e.state;
    return `<span class="compat-label compat-${escapeHtml(cls)}" title="${escapeHtml(tip)}">${STATE_MARK[e.state] ? STATE_MARK[e.state] + " " : ""}${escapeHtml(e.label || e.state)}</span>`;
  }

  function klondikeCell(e) {
    if (!e.klondike) return `<span class="profile-dim">–</span>`;
    const k = e.klondike;
    const gold = e.gold ? ` <span class="compat-label quality-label quality-klondike" title="level 3, and still routes with the Klondike profile loaded">⛏ Gold</span>` : "";
    const cls = k.hit === k.counted ? "profile-ok" : k.hit / k.counted >= COMPAT_LEVEL3_RATIO ? "profile-near" : "profile-bad";
    return `<span class="${cls}">${k.hit}/${k.counted}</span>${gold}`;
  }

  function summaryBox(p) {
    const own = p.summary, cum = p.cumulative || own;
    const testable = cum.total - cum.not_in_store - cum.untested - cum.not_testable;
    const bits = [
      `${cum.routes} route${cum.routes === 1 ? "" : "s"} (level 3)`,
      cum.gold ? `${cum.gold} ⛏ gold` : "",
      cum.fails ? `<span class="profile-bad">${cum.fails} fail${cum.fails === 1 ? "" : "s"}</span>` : "",
      cum.untested + cum.not_in_store ? `${cum.untested + cum.not_in_store} untested or not in store` : "",
    ].filter(Boolean).join(" · ");
    return `
      <a class="profile-box" href="#${encodeURIComponent(channel)}-${p.id}" data-jump="${p.id}">
        <span class="profile-box-title">${escapeHtml(PROFILE_TITLE[p.id] || p.name)}</span>
        <span class="profile-box-big">${cum.loads}<small>/${testable}</small></span>
        <span class="profile-box-sub">load (${pct(cum.loads, testable)}%) · ${cum.total} in total, ${own.total} added here</span>
        <span class="profile-box-sub">${bits}</span>
      </a>`;
  }

  function section(p) {
    const onlyProblems = problemsEl && problemsEl.checked;
    const rows = p.entries.filter((e) => !onlyProblems || isProblem(e));
    const body = rows.length ? rows.map((e) => `
      <tr class="${e.in_profile === false ? "profile-out" : ""}">
        <td>${nameCell(e)}</td>
        <td><span class="profile-kind profile-kind-${escapeHtml(e.kind)}">${escapeHtml(e.kind)}</span></td>
        <td class="profile-dim">${e.version ? escapeHtml(e.version) : "–"}</td>
        <td>${resultCell(e)}</td>
        <td>${klondikeCell(e)}</td>
      </tr>`).join("")
      : `<tr><td colspan="5" class="profile-dim">Everything here passes cleanly.</td></tr>`;
    const s = p.summary;
    return `
      <h2 class="detail-subhead" id="${escapeHtml(channel)}-${p.id}">${escapeHtml(PROFILE_TITLE[p.id] || p.name)}
        <span class="profile-head-count">${s.loads}/${s.total - s.not_in_store - s.untested - s.not_testable} load</span></h2>
      ${p.source ? `<p class="setup-note">${escapeHtml(p.source)}</p>` : ""}
      <div class="profile-table-wrap"><table class="profile-table">
        <thead><tr><th>Entry</th><th>Type</th><th>Version</th><th>Result</th><th>Klondike</th></tr></thead>
        <tbody>${body}</tbody>
      </table></div>`;
  }

  // --- Compare channels: one row per entry, one column per channel ---------
  // Columns in release order (stable → testing → alpha); arrows compare each
  // channel with testing, the installer's default.
  const COMPARE_ORDER = ["stable", "testing", "alpha"];

  function score(e) {
    if (!e || ["untested", "unsupported", "not_in_store"].includes(e.state)) return null;
    if (e.state === "fail") return 0;
    return e.golden ? 3 + e.golden.hit / e.golden.counted : 2;
  }

  function compactCell(e, ref) {
    if (!e) return `<td class="profile-dim">–</td>`;
    let text;
    if (e.state === "fail") text = e.level ? "✗ load" : "✗ install";
    else if (e.state === "not_in_store") text = "∅";
    else if (e.state === "untested") text = "·";
    else if (e.state === "unsupported") text = "–";
    else text = e.golden ? `✓ ${e.golden.hit}/${e.golden.counted}` : "✓ loads";
    const cls = e.state === "not_in_store" ? "untested" : e.state;
    const a = score(e), b = score(ref);
    const arrow = ref && ref !== e && a !== null && b !== null && Math.abs(a - b) > 0.001
      ? (a > b ? ` <span class="profile-ok" title="better than testing">▲</span>` : ` <span class="profile-bad" title="worse than testing">▼</span>`) : "";
    const k = e.klondike ? `<div class="profile-sub">K ${e.klondike.hit}/${e.klondike.counted}${e.gold ? " ⛏" : ""}</div>` : "";
    return `<td><span class="compat-label compat-${escapeHtml(cls)}" title="${escapeHtml(e.label || e.state)}${e.version ? " · v" + escapeHtml(e.version) : ""}">${escapeHtml(text)}</span>${arrow}${k}</td>`;
  }

  function differs(cells) {
    const sig = cells.filter(Boolean).map((e) => `${e.state}|${score(e)}|${e.klondike ? e.klondike.hit + "/" + e.klondike.counted : ""}`);
    return new Set(sig).size > 1;
  }

  function renderCompare() {
    const chans = COMPARE_ORDER.filter((c) => report.channels[c]);
    const profileIds = ["default", "extra", "klondike"];
    const prof = (ch, id) => (report.channels[ch].profiles || []).find((p) => p.id === id);
    const cell = (s) => {
      const testable = s.total - s.not_in_store - s.untested - s.not_testable;
      return `<td><strong>${s.loads}</strong><span class="profile-dim">/${testable}</span>
        <div class="profile-sub">${s.routes} level 3${s.gold ? ` · ${s.gold} ⛏` : ""}${s.fails ? ` · <span class="profile-bad">${s.fails} ✗</span>` : ""}</div></td>`;
    };
    metaEl.innerHTML = "Loads / testable, level 3 and ⛏ Gold, per profile (running totals) and channel. ▲▼: better or worse than testing.";
    summaryEl.innerHTML = `<div class="profile-table-wrap"><table class="profile-table profile-compare-sum">
      <thead><tr><th>Profile</th>${chans.map((c) => `<th>${escapeHtml(c)}</th>`).join("")}</tr></thead>
      <tbody>${profileIds.map((id) => `<tr><td><strong>${escapeHtml(PROFILE_TITLE[id])}</strong></td>${chans.map((c) => {
        const p = prof(c, id); return p ? cell(p.cumulative || p.summary) : `<td class="profile-dim">–</td>`;
      }).join("")}</tr>`).join("")}</tbody></table></div>`;

    const onlyDiff = problemsEl && problemsEl.checked;
    sectionsEl.innerHTML = profileIds.map((id) => {
      // An entry belongs to the profile it has on testing, else alpha, else stable.
      const rows = new Map();
      for (const c of ["testing", "alpha", "stable"].filter((x) => report.channels[x])) {
        for (const pid of profileIds) {
          for (const e of (prof(c, pid) || {}).entries || []) {
            const key = e.store_id || e.runtime_id;
            if (!rows.has(key)) rows.set(key, { profile: pid, entry: e, by: {} });
            rows.get(key).by[c] = e;
          }
        }
      }
      const mine = [...rows.values()].filter((r) => r.profile === id)
        .filter((r) => !onlyDiff || differs(chans.map((c) => r.by[c])));
      const body = mine.length ? mine.map((r) => `<tr>
          <td>${nameCell(r.entry)}</td>
          <td><span class="profile-kind profile-kind-${escapeHtml(r.entry.kind)}">${escapeHtml(r.entry.kind)}</span></td>
          ${chans.map((c) => compactCell(r.by[c], r.by.testing)).join("")}
        </tr>`).join("")
        : `<tr><td colspan="${2 + chans.length}" class="profile-dim">No differences between the channels.</td></tr>`;
      return `<h2 class="detail-subhead" id="compare-${id}">${escapeHtml(PROFILE_TITLE[id])}</h2>
        <div class="profile-table-wrap"><table class="profile-table profile-compare">
          <thead><tr><th>Entry</th><th>Type</th>${chans.map((c) => `<th>${escapeHtml(c)}</th>`).join("")}</tr></thead>
          <tbody>${body}</tbody></table></div>`;
    }).join("");
  }

  function render() {
    tabsEl.innerHTML = ["compare", ...TAB_ORDER.filter((c) => report.channels[c])].map((c) =>
      `<button type="button" role="tab" class="profile-tab${c === channel ? " active" : ""}" aria-selected="${c === channel}" data-channel="${c}">${c === "compare" ? "⇄ compare channels" : escapeHtml(c)}</button>`).join("");
    if (filterTextEl) {
      filterTextEl.textContent = channel === "compare" ? "Only show entries that differ between channels"
        : "Only show what does not pass cleanly";
    }
    if (channel === "compare") return renderCompare();
    const ch = report.channels[channel];
    metaEl.innerHTML = [ch.run_at ? `Routing run ${formatDate(ch.run_at)}` : "",
      ch.klondike_run_at ? `Klondike job ${formatDate(ch.klondike_run_at)}` : "",
      channel === "alpha" ? "alpha changes all the time" : "",
      channel === "stable" ? "stable is no longer offered by the installer" : ""].filter(Boolean).join(" · ");
    summaryEl.innerHTML = ch.profiles.map(summaryBox).join("");
    sectionsEl.innerHTML = ch.profiles.map(section).join("");
  }

  tabsEl.addEventListener("click", (ev) => {
    const b = ev.target.closest("[data-channel]");
    if (!b) return;
    channel = b.dataset.channel;
    history.replaceState(null, "", `#${channel}`);
    render();
  });
  if (problemsEl) problemsEl.addEventListener("change", render);

  const bust = `?t=${Date.now()}`;
  Promise.all([
    fetch(`compat/profile-report.json${bust}`, { cache: "no-store" }).then((r) => (r.ok ? r.json() : null)).catch(() => null),
    fetch(`skills.json${bust}`, { cache: "no-store" }).then((r) => (r.ok ? r.json() : null)).catch(() => null),
  ]).then(([rep, skills]) => {
    if (!rep || !rep.channels || !Object.keys(rep.channels).length) {
      sectionsEl.innerHTML = `<p class="setup-note">The overview shows here after the next test run.</p>`;
      return;
    }
    report = rep;
    for (const s of asArray(skills && skills.skills ? skills.skills : skills)) names[s.id] = s.name || s.id;
    channel = readHash() || "compare";
    render();
  });
})();
