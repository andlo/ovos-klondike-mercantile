// The Klondike profile per channel (issue #13), on the for-maintainers page:
// what is in it, what was left out and why, and the files to apply it.
// Read from compat/results.json ("klondike"), written by publish.py from the
// plan, so it always shows the profile the last test run used.
(function () {
  const box = document.querySelector("[data-klondike-profile]");
  if (!box) return;
  const code = (s) => `<code>${escapeHtml(s)}</code>`;

  function channelBlock(ch, k) {
    const p = k.profile || {};
    const curated = asArray(p.curated);
    const inList = curated.filter((c) => c.in).map((c) =>
      `<li>${code(c.id)}${c.function ? `: ${escapeHtml(c.function)}` : ""}${c.note ? ` <span class="setup-note">(${escapeHtml(c.note)})</span>` : ""}</li>`).join("");
    const out = Object.entries(p.left_out || {}).map(([id, why]) =>
      `<li>${code(id)}: ${escapeHtml(why)}</li>`).join("");
    const added = asArray(p.added_stages);
    const job = k.job || {};
    const results = Object.values(job.results || {});
    const members = results.filter((r) => r.member).length;
    const selfLine = job.error ? `not run: ${escapeHtml(job.error)}`
      : job.run_at ? `${members} store skills of the profile and ${results.length - members} other skills routed in one core, ${formatDate(job.run_at)}` : "not run yet";
    return `
      <h4 class="compat-subhead">${escapeHtml(ch)}</h4>
      <div class="compat-facts">
        ${renderFactRow("Installer", asArray(p.requirements)
          .filter((r) => r.startsWith("ovos-core[") && !asArray(p.extra_requirements).includes(r)).map(code).join(" ")
          + (asArray(p.extra_requirements).length ? ` + extra skills ${asArray(p.extra_requirements).map(code).join(" ")}` : ""))}
        ${renderFactRow("Pipeline", added.length ? `installer's, plus ${added.map(code).join(" ")}` : "the installer's, unchanged")}
        ${renderFactRow("Last run", selfLine)}
        ${renderFactRow("Apply it", `<a href="compat/klondike-profile-${encodeURIComponent(ch)}.txt">requirements</a> · <a href="compat/klondike-mycroft-${encodeURIComponent(ch)}.json">mycroft.conf pipeline</a>`)}
        ${renderFactRow("Reproduce a result", `install the job's <a href="compat/klondike-stack-${encodeURIComponent(ch)}.txt">exact stack</a> (same versions, plus every skill it routed) with ${code(`pip install -r klondike-stack-${ch}.txt`)}, set the pipeline, restart OVOS, then ${code("ovos-tui --run <skill_id>")}`)}
      </div>
      ${inList ? `<p class="setup-note">Curated:</p><ul class="compat-misses">${inList}</ul>` : ""}
      ${out ? `<p class="setup-note">Left out on ${escapeHtml(ch)}:</p><ul class="compat-misses">${out}</ul>` : ""}`;
  }

  function renderFactRow(label, value) {
    return `<div class="stat-row"><span class="stat-label">${escapeHtml(label)}</span><span class="stat-value">${value}</span></div>`;
  }

  loadCompatResults(`?t=${Date.now()}`).then((doc) => {
    const k = (doc && doc.klondike) || {};
    const chans = COMPAT_CHANNELS.filter((ch) => k[ch] && k[ch].profile);
    box.innerHTML = chans.length ? chans.map((ch) => channelBlock(ch, k[ch])).join("")
      : `<p class="setup-note">The profile shows here after the next test run.</p>`;
  });
})();
