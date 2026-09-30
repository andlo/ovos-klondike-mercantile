// ovos-test-report/1 checks for the browser: the paste-and-check box on the
// detail page (community reports, #9, and "check my report" for
// maintainers, #6). The format is the one ovos-tui-client's headless mode
// writes (manifest / summary / steps). The same rules and problem codes as
// scripts/reports/validate.py; tests/test_reports.py runs both on the same
// cases so they cannot drift. Nothing here trusts itself: the workflow
// checks every submitted report again.
const REPORT_SCHEMA = "ovos-test-report/1";
const REPORT_CHANNELS = ["stable", "testing", "alpha"];
const REPORT_CORE = ["ovos-core", "ovos-workshop", "ovos-padatious", "ovos-bus-client", "ovos-plugin-manager"];
const REPORT_LEVEL3_RATIO = 0.8;
const REPORT_STEP_STATUSES = ["pass", "fail", "timeout", "sent"];
const REPORT_CHECKED = ["pass", "fail", "timeout"];
const REPORT_MAX_STEPS = 2000;

const RE_IPV4 = /(?<![\d.])(?:(?:25[0-5]|2[0-4]\d|1?\d?\d)\.){3}(?:25[0-5]|2[0-4]\d|1?\d?\d)(?![\d.])/g;
const RE_EMAIL = /[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}/;
const RE_HOME = /(?:\/home\/|\/Users\/|C:\\Users\\)[^/\\\s]+/i;
const RE_SECRETISH = /(?:api[_-]?key|token|secret|password|passwd)\s*["':=]+\s*["']?[A-Za-z0-9_\-]{8,}/i;
const RE_LONG_TOKEN = /\b[A-Za-z0-9_\-]{40,}\b/;
const RE_VERSION_FIELDS = /^manifest\.(stack\.|skills\.[^.]+\.version$|machine\.python$)/;
const HARMLESS_IPS = ["127.0.0.1", "0.0.0.0"];

function reportNormalize(name) {
  return String(name == null ? "" : name).replace(/[-_.]+/g, "-").toLowerCase();
}

function reportProblem(list, code, field, message) {
  list.push({ code, field, message });
}

function* reportStrings(obj, path = "") {
  if (typeof obj === "string") yield [path, obj];
  else if (Array.isArray(obj)) for (let i = 0; i < obj.length; i++) yield* reportStrings(obj[i], `${path}[${i}]`);
  else if (obj && typeof obj === "object") for (const [k, v] of Object.entries(obj)) yield* reportStrings(v, path ? `${path}.${k}` : k);
}

function reportPrivacyProblems(report) {
  const out = [];
  for (const [field, text] of reportStrings(report)) {
    if (RE_VERSION_FIELDS.test(field)) continue;
    const ip = (text.match(RE_IPV4) || []).find((x) => !HARMLESS_IPS.includes(x));
    if (ip) reportProblem(out, "private_ip", field, `contains an IP address (${ip})`);
    if (RE_EMAIL.test(text)) reportProblem(out, "private_email", field, "contains an e-mail address");
    if (RE_HOME.test(text)) reportProblem(out, "private_path", field, "contains a path under a home directory (it names a user)");
    if (RE_SECRETISH.test(text) || RE_LONG_TOKEN.test(text)) reportProblem(out, "private_secret", field, "contains something that looks like a key or token");
  }
  const steps = Array.isArray(report.steps) ? report.steps : [];
  // Same truthiness as Python's step.get("replies"): a non-empty list or any truthy value.
  const i = steps.findIndex((s) => s && typeof s === "object"
    && (Array.isArray(s.replies) ? s.replies.length > 0 : !!s.replies));
  if (i >= 0) reportProblem(out, "private_replies", `steps[${i}].replies`, "contains OVOS's replies; share a report made without --report-replies");
  return out;
}

function isWhole(x) {
  return Number.isInteger(x) && x >= 0;
}

function reportStructureProblems(report) {
  const p = [];
  const isObj = (v) => v && typeof v === "object" && !Array.isArray(v);
  if (!isObj(report)) {
    reportProblem(p, "type", "", "the report is not a JSON object");
    return p;
  }
  if (report.schema !== REPORT_SCHEMA) reportProblem(p, "schema", "schema", `'schema' must be "${REPORT_SCHEMA}"`);
  const m = report.manifest;
  if (!isObj(m)) {
    reportProblem(p, "missing", "manifest", "'manifest' is missing");
    return p;
  }
  if (typeof m.tool !== "string") reportProblem(p, "missing", "manifest.tool", "'manifest.tool' is missing");
  if (typeof m.created_at !== "string" || Number.isNaN(Date.parse(m.created_at))) {
    reportProblem(p, "type", "manifest.created_at", "'manifest.created_at' is not an ISO date-time");
  }
  if (m.channel !== undefined && m.channel !== null && typeof m.channel !== "string") {
    reportProblem(p, "type", "manifest.channel", "'manifest.channel' must be a channel name or null");
  }
  if (!isObj(m.stack)) reportProblem(p, "type", "manifest.stack", "'manifest.stack' must be an object");
  if (!isObj(m.skills) || !Object.keys(m.skills).length) {
    reportProblem(p, "missing", "manifest.skills", "'manifest.skills' must name the tested skills");
  } else if (!Object.values(m.skills).every(isObj)) {
    reportProblem(p, "type", "manifest.skills", "every entry of 'manifest.skills' must be an object");
  }
  const steps = report.steps;
  if (!Array.isArray(steps) || steps.length > REPORT_MAX_STEPS) {
    reportProblem(p, "type", "steps", `'steps' must be a list of at most ${REPORT_MAX_STEPS} rows`);
    return p;
  }
  for (let i = 0; i < steps.length; i++) {
    const s = steps[i];
    if (!isObj(s) || typeof s.utterance !== "string" || !REPORT_STEP_STATUSES.includes(s.status)) {
      reportProblem(p, "type", `steps[${i}]`, "each step needs 'utterance' and a known 'status'");
      return p;
    }
  }
  const summary = report.summary;
  if (!isObj(summary)) {
    reportProblem(p, "missing", "summary", "'summary' is missing");
    return p;
  }
  for (const [key, status] of [["passed", "pass"], ["failed", "fail"], ["timed_out", "timeout"]]) {
    const n = steps.filter((s) => s.status === status).length;
    if (isWhole(summary[key]) && summary[key] !== n) {
      reportProblem(p, "inconsistent", `summary.${key}`, `'summary.${key}' says ${summary[key]}, the steps say ${n}`);
    }
  }
  if (isWhole(summary.steps) && summary.steps !== steps.length) {
    reportProblem(p, "inconsistent", "summary.steps", "'summary.steps' does not match the steps");
  }
  return p;
}

function reportSkillIdFor(report, packageName) {
  for (const [sid, info] of Object.entries((report.manifest || {}).skills || {})) {
    if (info && reportNormalize(info.package) === reportNormalize(packageName)) return sid;
  }
  return null;
}

function reportView(report, skillId) {
  const m = report.manifest || {};
  const info = (m.skills || {})[skillId] || {};
  const own = (report.steps || []).filter((s) => typeof s.expected === "string"
    && (s.expected === skillId || s.expected.startsWith(`${skillId}:`)));
  const checked = own.filter((s) => REPORT_CHECKED.includes(s.status));
  const routed = checked.filter((s) => s.status === "pass").length;
  const outcome = !checked.length || routed === checked.length ? "works" : routed ? "partly" : "doesnt_work";
  const cfg = m.config || {};
  const langs = [cfg.lang || m.lang, ...(cfg.secondary_langs || [])].filter(Boolean);
  const machine = m.machine || {};
  return {
    skill_id: skillId, package: info.package || null, version: info.version || null,
    loaded: info.active !== false, level: checked.length ? 3 : 2,
    checked: checked.length, routed, answered: own.filter((s) => s.answered).length,
    outcome, channel: m.channel == null ? null : m.channel, created_at: m.created_at || null, tool: m.tool || null,
    hardware: machine.model || machine.arch || "", languages: langs.slice(0, 10),
    notes: typeof report.notes === "string" ? report.notes.slice(0, 1000) : "",
    stt: String(cfg.stt || "").slice(0, 80), tts: String(cfg.tts || "").slice(0, 80),
  };
}

// A PEP 440 subset: enough for the constraints files (>=, >, <=, <, ==,
// !=, ~= on versions like 3.7.2a1, 1.3.4, 2.0.0.post1).
function pepParse(v) {
  const m = /^v?(\d+(?:\.\d+)*)(?:[-_.]?(a|b|rc|alpha|beta|c)[-_.]?(\d*))?(?:[-_.]?post[-_.]?(\d*))?(?:[-_.]?dev[-_.]?(\d*))?$/i.exec(String(v).trim());
  if (!m) return null;
  const pre = m[2] ? { a: 0, alpha: 0, b: 1, beta: 1, rc: 2, c: 2 }[m[2].toLowerCase()] : null;
  return { release: m[1].split(".").map(Number), pre: pre === null ? null : [pre, Number(m[3] || 0)],
    post: m[4] !== undefined ? Number(m[4] || 0) : null, dev: m[5] !== undefined ? Number(m[5] || 0) : null };
}

function pepKey(v) {
  // Sort key as packaging builds it: dev < pre < final < post.
  const r = [...v.release];
  while (r.length > 1 && r[r.length - 1] === 0) r.pop();
  const pre = v.pre ? v.pre : (v.dev !== null && v.post === null ? [-1, 0] : [3, 0]);
  return [r, pre, v.post === null ? -1 : v.post, v.dev === null ? Infinity : v.dev];
}

function pepCmp(a, b) {
  const ka = pepKey(a), kb = pepKey(b);
  const n = Math.max(ka[0].length, kb[0].length);
  for (let i = 0; i < n; i++) {
    const d = (ka[0][i] || 0) - (kb[0][i] || 0);
    if (d) return Math.sign(d);
  }
  for (let i = 0; i < 2; i++) if (ka[1][i] !== kb[1][i]) return Math.sign(ka[1][i] - kb[1][i]);
  if (ka[2] !== kb[2]) return Math.sign(ka[2] - kb[2]);
  if (ka[3] !== kb[3]) return ka[3] === Infinity ? 1 : kb[3] === Infinity ? -1 : Math.sign(ka[3] - kb[3]);
  return 0;
}

function pepAllowed(version, spec) {
  const v = pepParse(version);
  if (!v) return false;
  for (const part of spec.split(",").map((s) => s.trim()).filter(Boolean)) {
    const m = /^(~=|==|!=|>=|<=|>|<)\s*(.+)$/.exec(part);
    if (!m) return false;
    const [, op, rawTarget] = m;
    if (rawTarget.endsWith(".*")) {
      const prefix = rawTarget.slice(0, -2).split(".").map(Number);
      const same = prefix.every((x, i) => v.release[i] === x);
      if ((op === "==" && !same) || (op === "!=" && same)) return false;
      continue;
    }
    const t = pepParse(rawTarget);
    if (!t) return false;
    const c = pepCmp(v, t);
    let ok = { ">=": c >= 0, "<=": c <= 0, ">": c > 0, "<": c < 0, "==": c === 0, "!=": c !== 0 }[op];
    // PEP 440 exclusive comparisons: "<1.4.0" does not allow 1.4.0a1 and
    // ">1.4.0" does not allow 1.4.0.post1, unless the bound itself is one.
    const sameRelease = pepCmp({ ...v, pre: null, post: null, dev: null }, { ...t, pre: null, post: null, dev: null }) === 0;
    if (op === "<" && ok && !t.pre && !t.dev && (v.pre || v.dev !== null) && sameRelease) ok = false;
    if (op === ">" && ok && t.post === null && v.post !== null && sameRelease) ok = false;
    if (op === "~=") {
      const upper = t.release.slice(0, -1);
      upper[upper.length - 1] += 1;
      if (!(c >= 0 && pepCmp(v, { release: upper, pre: [-1, 0], post: null, dev: 0 }) < 0)) return false;
    } else if (!ok) return false;
  }
  return true;
}

function reportParseConstraints(text) {
  const pins = {};
  for (let line of String(text || "").split("\n")) {
    line = line.split("#")[0].trim();
    if (!line || line.startsWith("-") || line.includes(" @ ")) continue;
    const m = /^\s*([A-Za-z0-9][A-Za-z0-9._-]*)\s*(\[[^\]]*\])?\s*([^;]*)/.exec(line);
    if (m) pins[reportNormalize(m[1])] = m[3].trim();
  }
  return pins;
}

function reportMinor(v) {
  const p = pepParse(v);
  return p ? `${p.release[0]}.${p.release[1] || 0}` : null;
}

// Why the installed core versions are not what `channel` runs today
// ([] = they are): allowed by its live constraints AND the same
// major.minor as the channel installs today (alpha's constraints are
// floors only).
function reportStackMismatches(stack, channel, constraintsText, channelStack) {
  const out = [];
  const pins = reportParseConstraints(constraintsText);
  const now = Object.fromEntries(Object.entries(channelStack || {}).map(([k, val]) => [reportNormalize(k), val]));
  for (const pkg of REPORT_CORE) {
    const have = stack[reportNormalize(pkg)];
    if (!have) continue;
    const spec = pins[reportNormalize(pkg)];
    if (spec && !pepAllowed(have, spec)) {
      reportProblem(out, "old_stack", `manifest.stack.${pkg}`, `${pkg} ${have} is not allowed on ${channel}, which pins ${spec}`);
      continue;
    }
    const cur = now[reportNormalize(pkg)];
    if (cur && reportMinor(have) && reportMinor(have) !== reportMinor(cur)) {
      reportProblem(out, "old_stack", `manifest.stack.${pkg}`, `${pkg} ${have} is an older ${channel}: it runs ${cur} now`);
    }
  }
  return out;
}

// Same as validate.resolve_channel: the channel a report counts for is the
// one its installed versions match today; a declared one must agree.
function reportResolveChannel(report, constraints, channelStacks, hint) {
  const m = report.manifest || {};
  const stack = Object.fromEntries(Object.entries(m.stack || {}).map(([k, val]) => [reportNormalize(k), val]));
  const out = [];
  if (!stack["ovos-core"]) {
    reportProblem(out, "no_stack", "manifest.stack", "the report has no installed versions (run the tool on the device itself)");
    return [null, null, out];
  }
  const declared = REPORT_CHANNELS.includes(m.channel) ? m.channel : (REPORT_CHANNELS.includes(hint) ? hint : null);
  constraints = constraints || {};
  channelStacks = channelStacks || {};
  if (declared) {
    if (constraints[declared] === null || constraints[declared] === undefined) {
      reportProblem(out, "no_constraints", "manifest.channel", `the ${declared} constraints could not be read`);
      return [null, null, out];
    }
    const mism = reportStackMismatches(stack, declared, constraints[declared], channelStacks[declared]);
    const source = REPORT_CHANNELS.includes(m.channel) ? "declared" : "file name";
    return mism.length ? [null, null, mism] : [declared, source, []];
  }
  const fits = REPORT_CHANNELS.filter((ch) => constraints[ch] !== null && constraints[ch] !== undefined
    && !reportStackMismatches(stack, ch, constraints[ch], channelStacks[ch]).length);
  if (fits.length === 1) return [fits[0], "installed versions", []];
  const what = !fits.length ? "match no channel as it is today" : `match more than one channel (${fits.join(", ")})`;
  reportProblem(out, "no_channel", "manifest.channel", `no channel was given and the installed versions ${what}`);
  return [null, null, out];
}

function reportCountingProblems(v) {
  const out = [];
  if (!v.loaded) reportProblem(out, "not_loaded", "manifest.skills", "the skill was not active");
  if (v.checked && v.routed / v.checked < REPORT_LEVEL3_RATIO) {
    reportProblem(out, "below_level3", "steps", `${v.routed}/${v.checked} reached it, below the ${REPORT_LEVEL3_RATIO * 100}% level 3 needs`);
  }
  return out;
}

// Same contract as validate.check(): constraints and channelStacks per
// channel, fetched live by the caller.
function checkReport(report, { packageName, latestVersion, constraints, channelStacks, channelHint } = {}) {
  let problems = reportStructureProblems(report);
  let v = null;
  if (!problems.length) {
    problems = problems.concat(reportPrivacyProblems(report));
    const sid = packageName ? reportSkillIdFor(report, packageName) : Object.keys(report.manifest.skills)[0];
    if (sid === null) {
      const tested = Object.values(report.manifest.skills).map((i) => String((i || {}).package)).join(", ");
      reportProblem(problems, "wrong_skill", "manifest.skills", `the report tested ${tested}, not ${packageName}`);
    } else {
      v = reportView(report, sid);
      if (!v.version) reportProblem(problems, "missing", "manifest.skills", "the report has no version for the skill (run the tool on the device itself)");
    }
  }
  if (problems.length) return { status: "invalid", passes: false, problems, view: v };
  const stale = [];
  if (latestVersion && v.version !== latestVersion) {
    reportProblem(stale, "old_version", "manifest.skills", `it tested ${v.version}; the current release is ${latestVersion}`);
  }
  const [channel, source, channelProblems] = reportResolveChannel(report, constraints, channelStacks, channelHint);
  v.channel = channel;
  v.channel_source = source;
  const all = stale.concat(channelProblems);
  const notPassing = reportCountingProblems(v);
  return { status: all.length ? "stale" : "current", passes: !notPassing.length && v.outcome === "works",
    problems: all.concat(notPassing), view: v };
}

if (typeof module !== "undefined") module.exports = { checkReport, pepAllowed };
