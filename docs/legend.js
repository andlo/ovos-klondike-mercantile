// "What we tested" legend: every channel label a card, a detail page or a
// README badge can show, drawn by the same code that draws the real ones
// (compatFromRecord, renderCompatLabels in shared.js), so the explanation
// cannot drift from the labels. Rendered into any <div data-test-legend>.
// Needs shared.js.

const LEGEND_ROWS = [
  { rec: { status: "pass", level: 3, routing: { golden: { status: "ok", hit: 14, counted: 14 } } },
    what: "Level 3: its own golden utterances were sent with the OVOS installer's default skills loaded, and they all reached it. The best result." },
  { rec: { status: "pass", level: 2, routing: { golden: { status: "ok", hit: 9, counted: 14 } } },
    what: "Loads, but fewer than 80% of its golden utterances reached it: a default skill took some, or none answered. The detail page lists each miss and who took it." },
  { rec: { status: "pass", level: 2 },
    what: "Level 2: installs under the channel's own versions and loads in a test core. It has no golden utterances in its release, so routing wasn't measured." },
  { rec: { status: "pass", level: 2, languages_booted: ["en-US", "da-DK", "de-DE"], languages_missing: ["de-DE"] },
    what: "Loads, but one or more of its languages fail to load or register nothing. The detail page names them." },
  { rec: { status: "fail", level: 1 },
    what: "Installs, but fails to load (an import error, a crash in its own code). The detail page shows the reason and a log excerpt." },
  { rec: { status: "fail", level: 0 },
    what: "Doesn't install next to the channel's own versions (a dependency conflict). The detail page says which." },
  { rec: { status: "needs_config", level: 1 },
    what: "Not a failure: its own error says it needs an API key, an account or similar before it can start." },
  { rec: { status: "needs_device", level: 1 },
    what: "Not a failure: loading waits for something only a real device has (network, GUI). The detail page shows where." },
  { rec: { status: "unsupported", level: 1 },
    what: "Not a failure: this channel can't run this kind of package at all (stable has no loader for third-party pipeline plugins)." },
];

function legendCardLabel(ch, c) {
  const mark = { fail: "✗", unsupported: "–" }[c.state] || "✓";
  return `<span class="compat-label compat-${escapeHtml(c.state)}">${mark} ${escapeHtml(ch)}</span>`;
}

function renderTestLegend() {
  const rows = LEGEND_ROWS.map(({ rec, what }) => {
    const c = compatFromRecord(rec);
    return `<tr>
      <td>${legendCardLabel("testing", c)}</td>
      <td><span class="compat-label compat-${escapeHtml(c.state)}">${escapeHtml(c.label)}</span></td>
      <td>${escapeHtml(what)}</td></tr>`;
  }).join("");
  const maintainer = renderCompatLabels({ compat: { channels: { alpha: { state: "unsupported", label: "needs config", level: 1 } } },
    reports: { alpha: { maintainer: "pass", maintainer_level: 3, works: 0 } } });
  const users = renderCompatLabels({ compat: { channels: { testing: compatFromRecord(LEGEND_ROWS[2].rec) } },
    reports: { testing: { works: 4 } } });
  return `
    <table class="legend-table">
      <thead><tr><th>On a card</th><th>On the detail page and the README badge</th><th>Meaning</th></tr></thead>
      <tbody>
        ${rows}
        <tr><td>${maintainer}</td><td>maintainer-tested, level 3</td>
          <td>We couldn't test it on this channel, but its maintainer did, on their own configured device, and published the report in the skill's repo. Shown in its own colour so it's never mistaken for our result.</td></tr>
        <tr><td>${users}</td><td>Confirmed by 4 users</td>
          <td>Users who ran it on their own setups sent reports saying it works. The detail page shows each setup (hardware, language, STT, TTS), and reports saying it doesn't work too.</td></tr>
      </tbody>
    </table>
    <p class="setup-note">Each card shows one label per tested channel: <strong>testing</strong> (what the OVOS installer installs by default),
      <strong>alpha</strong> and <strong>stable</strong>. Hover a label for the version and date tested. A channel we haven't tested yet shows no label.
      The README badge a maintainer can add says the same as the detail page, e.g.
      <img class="legend-shield" alt="ovos testing: ✓ 14/14 golden" src="https://img.shields.io/badge/ovos%20testing-%E2%9C%93%2014%2F14%20golden-brightgreen"></p>`;
}

document.querySelectorAll("[data-test-legend]").forEach((el) => { el.innerHTML = renderTestLegend(); });
