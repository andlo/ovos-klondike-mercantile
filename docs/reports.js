// ovos-test-report/1 checks for the browser: the paste-and-check box on the
// detail page (community reports, #9, and "check my report" for
// maintainers, #6). The same rules and problem codes as
// scripts/reports/validate.py; test/test_reports_parity.py runs both on the
// same cases so they cannot drift. Nothing here trusts itself: the workflow
// checks every submitted report again.
const REPORT_SCHEMA = "ovos-test-report/1";
const REPORT_CHANNELS = ["stable", "testing", "alpha"];
const REPORT_CORE = ["ovos-core", "ovos-workshop", "ovos-padatious", "ovos-bus-client", "ovos-plugin-manager"];
const REPORT_LEVEL3_RATIO = 0.8;
const REPORT_OUTCOMES = ["works", "partly", "doesnt_work"];

const RE_IPV4 = /(?<![\d.])(?:(?:25[0-5]|2[0-4]\d|1?\d?\d)\.){3}(?:25[0-5]|2[0-4]\d|1?\d?\d)(?![\d.])/g;
const RE_EMAIL = /[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}/;
const RE_HOME = /(?:\/home\/|\/Users\/|C:\\Users\\)[^/\\\s]+/i;
const RE_SECRETISH = /(?:api[_-]?key|token|secret|password|passwd)\s*["':=]+\s*["']?[A-Za-z0-9_\-]{8,}/i;
const RE_LONG_TOKEN = /\b[A-Za-z0-9_\-]{40,}\b/;
const HARMLESS_IPS = ["127.0.0.1", "0.0.0.0"];

function reportNormalize(name) {
  return String(name).replace(/[-_.]+/g, "-").toLowerCase();
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
    if (field.startsWith("stack") || field === "skill.version") continue;
    const ip = (text.match(RE_IPV4) || []).find((x) => !HARMLESS_IPS.includes(x));
    if (ip) reportProblem(out, "private_ip", field, `contains an IP address (${ip})`);
    if (RE_EMAIL.test(text)) reportProblem(out, "private_email", field, "contains an e-mail address");
    if (RE_HOME.test(text)) reportProblem(out, "private_path", field, "contains a path under a home directory (it names a user)");
    if (RE_SECRETISH.test(text) || RE_LONG_TOKEN.test(text)) reportProblem(out, "private_secret", field, "contains something that looks like a key or token");
  }
  return out;
}

function isWhole(x) {
  return Number.isInteger(x) && x >= 0;
}

function reportStructureProblems(report) {
  const p = [];
  if (!report || typeof report !== "object" || Array.isArray(report)) {
    reportProblem(p, "type", "", "the report is not a JSON object");
    return p;
  }
  const need = (field, check, what) => {
    if (report[field] === undefined || report[field] === null) {
      reportProblem(p, "missing", field, `'${field}' is missing`);
      return undefined;
    }
    if (!check(report[field])) {
      reportProblem(p, "type", field, `'${field}' has the wrong type`);
      return undefined;
    }
    return report[field];
  };
  const isObj = (v) => v && typeof v === "object" && !Array.isArray(v);
  if (report.schema !== REPORT_SCHEMA) reportProblem(p, "schema", "schema", `'schema' must be "${REPORT_SCHEMA}"`);
  need("tool", (v) => typeof v === "string");
  const created = need("created_at", (v) => typeof v === "string");
  if (created && Number.isNaN(Date.parse(created))) reportProblem(p, "type", "created_at", "'created_at' is not an ISO date-time");
  if (![...REPORT_CHANNELS, "unknown"].includes(report.channel)) reportProblem(p, "type", "channel", "'channel' must be stable, testing, alpha or unknown");
  const skill = need("skill", isObj);
  if (skill) for (const k of ["package", "version"]) {
    if (typeof skill[k] !== "string" || !skill[k]) reportProblem(p, "missing", `skill.${k}`, `'skill.${k}' is missing`);
  }
  const stack = need("stack", isObj);
  if (stack && typeof stack["ovos-core"] !== "string") reportProblem(p, "missing", "stack.ovos-core", "'stack' must name the ovos-core version");
  if (![2, 3].includes(report.level)) reportProblem(p, "type", "level", "'level' must be 2 or 3");
  const loaded = need("loaded", isObj);
  if (loaded && typeof loaded.ok !== "boolean") reportProblem(p, "missing", "loaded.ok", "'loaded.ok' must be true or false");
  if ("outcome" in report && !REPORT_OUTCOMES.includes(report.outcome)) reportProblem(p, "type", "outcome", "'outcome' must be works, partly or doesnt_work");
  const utt = report.utterances;
  if (report.level === 3 && !isObj(utt)) reportProblem(p, "missing", "utterances", "a level 3 report needs 'utterances'");
  if (isObj(utt)) {
    if (!isWhole(utt.total) || !isWhole(utt.routed)) {
      reportProblem(p, "type", "utterances", "'utterances.total' and '.routed' must be whole numbers");
    } else if (utt.routed > utt.total || (Number.isInteger(utt.answered) && utt.answered > utt.total)) {
      reportProblem(p, "inconsistent", "utterances", "more utterances routed or answered than were run");
    } else if (Array.isArray(report.results) && report.results.length > utt.total) {
      reportProblem(p, "inconsistent", "results", "more results than utterances run");
    }
  }
  return p;
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

function reportStaleReasons(report, latestVersion, constraintsText, channelStack) {
  const out = [];
  const version = (report.skill || {}).version;
  if (latestVersion && version !== latestVersion) {
    reportProblem(out, "old_version", "skill.version", `it tested ${version}; the current release is ${latestVersion}`);
  }
  if (!REPORT_CHANNELS.includes(report.channel)) {
    reportProblem(out, "no_channel", "channel", "the channel is unknown, so it cannot count for one");
    return out;
  }
  if (constraintsText === null || constraintsText === undefined) {
    reportProblem(out, "no_constraints", "channel", `the ${report.channel} constraints could not be read`);
    return out;
  }
  const pins = reportParseConstraints(constraintsText);
  const stack = Object.fromEntries(Object.entries(report.stack || {}).map(([k, v]) => [reportNormalize(k), v]));
  const now = Object.fromEntries(Object.entries(channelStack || {}).map(([k, v]) => [reportNormalize(k), v]));
  for (const pkg of REPORT_CORE) {
    const have = stack[reportNormalize(pkg)], spec = pins[reportNormalize(pkg)];
    if (have && spec && !pepAllowed(have, spec)) {
      reportProblem(out, "old_stack", `stack.${pkg}`, `${pkg} ${have} is no longer allowed on ${report.channel}, which now pins ${spec}`);
    }
  }
  for (const pkg of REPORT_CORE) {
    const have = stack[reportNormalize(pkg)], cur = now[reportNormalize(pkg)];
    if (have && cur && reportMinor(have) && reportMinor(have) !== reportMinor(cur)
        && !out.some((p) => p.field === `stack.${pkg}`)) {
      reportProblem(out, "old_stack", `stack.${pkg}`, `${pkg} ${have} is an older ${report.channel}: it runs ${cur} now`);
    }
  }
  return out;
}

function reportCountingProblems(report) {
  const out = [];
  if (!(report.loaded || {}).ok) reportProblem(out, "not_loaded", "loaded.ok", "the skill did not load");
  const utt = report.utterances || {};
  if (report.level === 3 && utt.total) {
    if ((utt.routed || 0) / utt.total < REPORT_LEVEL3_RATIO) {
      reportProblem(out, "below_level3", "utterances", `${utt.routed || 0}/${utt.total} routed, below the ${REPORT_LEVEL3_RATIO * 100}% level 3 needs`);
    }
  }
  return out;
}

// Same contract as validate.check().
function checkReport(report, { packageName, latestVersion, constraintsText, channelStack } = {}) {
  let problems = reportStructureProblems(report);
  if (!problems.length) {
    problems = problems.concat(reportPrivacyProblems(report));
    const pkg = (report.skill || {}).package;
    if (packageName && reportNormalize(pkg) !== reportNormalize(packageName)) {
      reportProblem(problems, "wrong_skill", "skill.package", `the report is about ${pkg}, not ${packageName}`);
    }
  }
  if (problems.length) return { status: "invalid", passes: false, problems };
  const stale = reportStaleReasons(report, latestVersion, constraintsText, channelStack);
  const notPassing = reportCountingProblems(report);
  return {
    status: stale.length ? "stale" : "current",
    passes: !notPassing.length && (report.outcome || "works") === "works",
    problems: stale.concat(notPassing),
  };
}

if (typeof module !== "undefined") module.exports = { checkReport, pepAllowed };
