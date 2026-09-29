// Detail page: test reports from people, next to our own channel tests.
//   maintainer (#6): the maintainer's own report, from their repo
//   community (#9): reports from users, submitted through the box below
// Everything a report contains is shown through escapeHtml; the page never
// renders report text as HTML. Loaded before detail.js.

let reportsDoc = null; // docs/reports/index.json
const REPO_NEW_ISSUE = "https://github.com/andlo/ovos-klondike-mercantile/issues/new";
const CONSTRAINTS_RAW = "https://raw.githubusercontent.com/OpenVoiceOS/ovos-releases/main/constraints-";
const MAX_ISSUE_URL = 7500;
const OUTCOME_TEXT = { works: "works", partly: "partly", doesnt_work: "doesn't work" };

function peopleSummary(skill, ch) {
  return ((reportsDoc && reportsDoc.entries && reportsDoc.entries[skill.id]) || {})[ch] || null;
}

function reportChannels(skill) {
  const e = (reportsDoc && reportsDoc.entries && reportsDoc.entries[skill.id]) || {};
  return COMPAT_CHANNELS.filter((ch) => e[ch]);
}

function renderMaintainerReport(skill, m) {
  if (!m) return "";
  const file = m.source && skill.source ? `${skill.source}/blob/HEAD/${m.source}` : null;
  const link = file ? ` · <a href="${escapeHtml(file)}" target="_blank" rel="noopener">report</a>` : "";
  if (m.status === "invalid") {
    return `<div class="people-row people-invalid">Maintainer report not shown: ${escapeHtml(asArray(m.problems).join("; "))}${link}</div>`;
  }
  const counts = m.checked ? ` · ${m.routed}/${m.checked} reached it, ${m.answered} answered` : "";
  const when = m.created_at ? ` · ${formatDate(m.created_at)}` : "";
  const setup = (m.setup || m.hardware) ? `<div class="people-setup">${escapeHtml([m.hardware, m.setup].filter(Boolean).join(" · "))}</div>` : "";
  if (m.status === "stale") {
    return `<div class="people-row people-stale">Maintainer-tested v${escapeHtml(m.version)}, level ${escapeHtml(String(m.level))}${escapeHtml(counts)}${escapeHtml(when)}${link}
      <div class="people-why">Not counted: ${escapeHtml(asArray(m.problems)[0] || "out of date")}</div>${setup}</div>`;
  }
  const mark = m.passes ? "✓" : "✗";
  return `<div class="people-row people-maintainer">${mark} Maintainer-tested on their own device, level ${escapeHtml(String(m.level))}${escapeHtml(counts)}${escapeHtml(when)}${link}${setup}</div>`;
}

function renderCommunityReports(c) {
  if (!c) return "";
  const current = asArray(c.reports).filter((r) => r.current);
  const rows = {};
  for (const r of current) {
    const key = [r.hardware || "unspecified hardware", asArray(r.languages)[0] || ""].filter(Boolean).join(" · ");
    rows[key] = rows[key] || { works: 0, partly: 0, doesnt_work: 0, reports: [] };
    rows[key][r.outcome] += 1;
    rows[key].reports.push(r);
  }
  const table = Object.keys(rows).length ? `
    <table class="people-matrix"><thead><tr><th>Setup</th><th>✓</th><th>partly</th><th>✗</th></tr></thead><tbody>
      ${Object.entries(rows).map(([setup, v]) => `
        <tr><td>${escapeHtml(setup)}</td><td>${v.works || ""}</td><td>${v.partly || ""}</td><td>${v.doesnt_work || ""}</td></tr>
        <tr class="people-detail"><td colspan="4">${fold(`${v.reports.length} ${v.reports.length === 1 ? "report" : "reports"}`,
          `<ul class="people-list">${v.reports.map(renderOneReport).join("")}</ul>`)}</td></tr>`).join("")}
    </tbody></table>` : "";
  const confirmations = c.works ? `<strong>Confirmed by ${c.works} ${c.works === 1 ? "user" : "users"}</strong>` : "";
  const bad = c.doesnt_work ? ` · ${c.doesnt_work} ${c.doesnt_work === 1 ? "report says" : "reports say"} it doesn't work` : "";
  const history = c.history ? ` <span class="setup-note">(${c.history} older ${c.history === 1 ? "report" : "reports"} for an earlier version or channel, not counted)</span>` : "";
  if (!table && !history) return "";
  return `<div class="people-row people-community">${confirmations}${escapeHtml(bad)}${history}${table}</div>`;
}

function renderOneReport(r) {
  const bits = [r.user ? `@${r.user}` : "", r.created_at ? formatDate(r.created_at) : "", `v${r.version}`,
    r.checked ? `${r.routed}/${r.checked} reached it` : ""].filter(Boolean).join(" · ");
  return `<li><span class="people-outcome people-${escapeHtml(r.outcome)}">${escapeHtml(OUTCOME_TEXT[r.outcome] || r.outcome)}</span>
    ${escapeHtml(bits)}${r.notes ? `<div class="people-setup">${escapeHtml(r.notes)}</div>` : ""}</li>`;
}

function renderPeopleReports(skill, ch) {
  const s = peopleSummary(skill, ch);
  if (!s) return "";
  return renderMaintainerReport(skill, s.maintainer) + renderCommunityReports(s.community);
}

// ---- Submit / check a report -------------------------------------------
// A static page cannot post anything: the report is checked here with the
// same rules the workflow applies (reports.js), then the GitHub issue form
// opens prefilled, and the user submits it as themselves. Maintainers use
// the same box as "check my report" before committing theirs.

function renderReportBox(skill) {
  if (!skill.compat) return "";
  return fold("Submit a test report", `
    <p class="setup-note">Tested this skill on your own OVOS device? Paste the report your test tool wrote
      (an <code>ovos-test-report/1</code> file: <code>ovos-tui --run &lt;skill_id&gt; --report -</code>). It is checked here first, then
      GitHub opens with it filled in and you submit it as yourself. Maintainers: use this to check your
      report before you commit it as <code>test/reports/&lt;channel&gt;.json</code>.</p>
    <textarea id="report-input" class="report-input" rows="8" spellcheck="false" placeholder='{"schema": "ovos-test-report/1", ...}'></textarea>
    <div class="report-actions">
      <button type="button" id="report-check" class="detail-link-btn">Check report</button>
      <button type="button" id="report-submit" class="detail-link-btn" hidden>Submit on GitHub</button>
    </div>
    <div id="report-result" class="report-result" aria-live="polite"></div>
  `);
}

async function fetchText(url) {
  try {
    const res = await fetch(url, { cache: "no-store" });
    return res.ok ? await res.text() : null;
  } catch (e) {
    return null;
  }
}

async function latestRelease(skill) {
  try {
    const res = await fetch(`https://pypi.org/pypi/${encodeURIComponent(skill.package_name)}/json`);
    if (res.ok) return (await res.json()).info.version;
  } catch (e) { /* fall back to the feed */ }
  return skill.pypi_version || null;
}

function showReportResult(el, heading, problems, cls) {
  el.className = `report-result ${cls}`;
  el.textContent = "";
  const h = document.createElement("p");
  h.textContent = heading;
  el.appendChild(h);
  if (problems.length) {
    const ul = document.createElement("ul");
    for (const p of problems) {
      const li = document.createElement("li");
      li.textContent = p.field ? `${p.field}: ${p.message}` : p.message;
      ul.appendChild(li);
    }
    el.appendChild(ul);
  }
}

function wireReportBox(skill) {
  const input = document.getElementById("report-input");
  if (!input) return;
  const checkBtn = document.getElementById("report-check");
  const submitBtn = document.getElementById("report-submit");
  const out = document.getElementById("report-result");
  let checked = null;
  input.addEventListener("input", () => { submitBtn.hidden = true; checked = null; });
  checkBtn.addEventListener("click", async () => {
    submitBtn.hidden = true;
    let report;
    try {
      report = JSON.parse(input.value);
    } catch (e) {
      showReportResult(out, `That is not valid JSON (${e.message}). Paste the whole file, unchanged.`, [], "report-invalid");
      return;
    }
    showReportResult(out, "Checking against the current release and channel…", [], "report-pending");
    // Every channel's constraints, live, and what each channel installs
    // today (our own compat run): the report counts for the channel its
    // installed versions match now.
    const texts = await Promise.all(REPORT_CHANNELS.map((c) => fetchText(`${CONSTRAINTS_RAW}${c}.txt`)));
    const constraints = Object.fromEntries(REPORT_CHANNELS.map((c, i) => [c, texts[i]]));
    const stacks = Object.fromEntries(REPORT_CHANNELS.map((c) =>
      [c, ((((compatDoc || {}).channels || {})[c] || {}).stack || {}).packages || null]));
    const res = checkReport(report, { packageName: skill.package_name, latestVersion: await latestRelease(skill),
      constraints, channelStacks: stacks });
    const ch = res.view && res.view.channel;
    const how = res.view && res.view.channel_source === "installed versions" ? " (found from the installed versions)" : "";
    if (res.status === "invalid") {
      showReportResult(out, "This report can't be accepted:", res.problems, "report-invalid");
    } else if (res.status === "stale") {
      showReportResult(out, "The report is well-formed, but it would only count as history. Re-run the test on the current release and channel:", res.problems, "report-stale");
    } else {
      const v = res.view;
      const outcome = v.loaded ? v.outcome : "doesnt_work";
      const measured = v.checked ? ` (${v.routed}/${v.checked} sentences reached it)` : "";
      const verdict = res.passes ? `It counts as a confirmation that the skill works${measured}` : `It counts as a "${OUTCOME_TEXT[outcome]}" report${measured}`;
      showReportResult(out, `Looks good. ${verdict} on ${ch}${how}.`, res.problems, "report-ok");
      checked = report;
      submitBtn.hidden = false;
    }
  });
  submitBtn.addEventListener("click", async () => {
    if (!checked) return;
    // Compact in the link (a 7-step report is ~4 KB compact, ~7 KB indented);
    // indented on the clipboard, where length does not matter.
    const text = JSON.stringify(checked, null, 2);
    const params = new URLSearchParams({ template: "test-report.yml", title: `Test report: ${skill.id}`, entry: skill.id });
    let url = `${REPO_NEW_ISSUE}?${params}&report=${encodeURIComponent(JSON.stringify(checked))}`;
    if (url.length > MAX_ISSUE_URL) {
      url = `${REPO_NEW_ISSUE}?${params}`;
      try { await navigator.clipboard.writeText(text); } catch (e) { /* the user can copy it from the box */ }
      showReportResult(out, "The report is too long for a link, so it was copied to your clipboard: paste it into the Report field on the GitHub page that opens.", [], "report-ok");
    }
    window.open(url, "_blank", "noopener");
  });
}
