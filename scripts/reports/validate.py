"""Check an ovos-test-report/1 file (issue #6 maintainer reports, #9
community reports).

One implementation of the rules, used by the crawler (maintainer reports in
a skill's repo), the issue workflow (community reports) and
`check_report.py` (maintainers, before they commit). docs/reports.js holds
the same rules for the paste-and-check box; tests keep the two in step.

A report is:
  invalid  malformed, inconsistent, or carries private data: never shown
  stale    well-formed, but for an older skill version or a core stack
           the channel no longer allows: shown as history, never counted
  current  counts

Private data is rejected, not scrubbed: the report was meant to be clean
when it left the device, and a store that quietly edits it would publish
something the tester never saw.
"""
import re
from datetime import datetime

SCHEMA = "ovos-test-report/1"
CHANNELS = ("stable", "testing", "alpha")
# The packages whose versions decide "same channel, loosely" (#6): a report
# stays current while the channel's constraints still allow each of these.
CORE_PACKAGES = ("ovos-core", "ovos-workshop", "ovos-padatious", "ovos-bus-client",
                 "ovos-plugin-manager")
LEVEL3_RATIO = 0.8
OUTCOMES = ("works", "partly", "doesnt_work")

IPV4 = re.compile(r"(?<![\d.])(?:(?:25[0-5]|2[0-4]\d|1?\d?\d)\.){3}(?:25[0-5]|2[0-4]\d|1?\d?\d)(?![\d.])")
EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
HOME = re.compile(r"(?:/home/|/Users/|C:\\Users\\)[^/\\\s]+", re.I)
SECRETISH = re.compile(r"(?i)(?:api[_-]?key|token|secret|password|passwd)\s*[\"':=]+\s*[\"']?[A-Za-z0-9_\-]{8,}")
LONG_TOKEN = re.compile(r"\b[A-Za-z0-9_\-]{40,}\b")
# Addresses that are not a device's own: loopback and documentation ranges.
HARMLESS_IPS = ("127.0.0.1", "0.0.0.0")


def normalize(name):
    return re.sub(r"[-_.]+", "-", str(name)).lower()


def _problem(problems, code, field, message):
    problems.append({"code": code, "field": field, "message": message})


def _strings(obj, path=""):
    """Every string in the report with its field path, for the privacy scan."""
    if isinstance(obj, str):
        yield path, obj
    elif isinstance(obj, dict):
        for k, v in obj.items():
            yield from _strings(v, f"{path}.{k}" if path else str(k))
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            yield from _strings(v, f"{path}[{i}]")


def privacy_problems(report):
    out = []
    for field, text in _strings(report):
        # Version strings (stack, skill.version) look like dotted numbers.
        if field.startswith("stack") or field == "skill.version":
            continue
        for ip in IPV4.findall(text):
            if ip not in HARMLESS_IPS:
                _problem(out, "private_ip", field, f"contains an IP address ({ip})")
                break
        if EMAIL.search(text):
            _problem(out, "private_email", field, "contains an e-mail address")
        if HOME.search(text):
            _problem(out, "private_path", field, "contains a path under a home directory (it names a user)")
        if SECRETISH.search(text) or LONG_TOKEN.search(text):
            _problem(out, "private_secret", field, "contains something that looks like a key or token")
    return out


def _check_type(problems, report, field, kind, required=True):
    v = report.get(field)
    if v is None:
        if required:
            _problem(problems, "missing", field, f"'{field}' is missing")
        return None
    if not isinstance(v, kind) or (kind is int and isinstance(v, bool)):
        _problem(problems, "type", field, f"'{field}' has the wrong type")
        return None
    return v


def structure_problems(report):
    """Shape and internal consistency. Hand-written rather than a JSON Schema
    library, so the browser can apply the very same rules without one; the
    published schema (docs/schemas/ovos-test-report-1.json) documents them."""
    p = []
    if not isinstance(report, dict):
        _problem(p, "type", "", "the report is not a JSON object")
        return p
    if report.get("schema") != SCHEMA:
        _problem(p, "schema", "schema", f"'schema' must be \"{SCHEMA}\"")
    _check_type(p, report, "tool", str)
    created = _check_type(p, report, "created_at", str)
    if created:
        try:
            datetime.fromisoformat(created.replace("Z", "+00:00"))
        except ValueError:
            _problem(p, "type", "created_at", "'created_at' is not an ISO date-time")
    channel = report.get("channel")
    if channel not in CHANNELS + ("unknown",):
        _problem(p, "type", "channel", "'channel' must be stable, testing, alpha or unknown")
    skill = _check_type(p, report, "skill", dict)
    if skill is not None:
        for k in ("package", "version"):
            if not isinstance(skill.get(k), str) or not skill.get(k):
                _problem(p, "missing", f"skill.{k}", f"'skill.{k}' is missing")
    stack = _check_type(p, report, "stack", dict)
    if stack is not None and not isinstance(stack.get("ovos-core"), str):
        _problem(p, "missing", "stack.ovos-core", "'stack' must name the ovos-core version")
    if report.get("level") not in (2, 3):
        _problem(p, "type", "level", "'level' must be 2 or 3")
    loaded = _check_type(p, report, "loaded", dict)
    if loaded is not None and not isinstance(loaded.get("ok"), bool):
        _problem(p, "missing", "loaded.ok", "'loaded.ok' must be true or false")
    if "outcome" in report and report["outcome"] not in OUTCOMES:
        _problem(p, "type", "outcome", "'outcome' must be works, partly or doesnt_work")
    utt = report.get("utterances")
    if report.get("level") == 3 and not isinstance(utt, dict):
        _problem(p, "missing", "utterances", "a level 3 report needs 'utterances'")
    if isinstance(utt, dict):
        total, routed = utt.get("total"), utt.get("routed")
        if not all(isinstance(x, int) and not isinstance(x, bool) and x >= 0 for x in (total, routed)):
            _problem(p, "type", "utterances", "'utterances.total' and '.routed' must be whole numbers")
        elif routed > total or (isinstance(utt.get("answered"), int) and utt["answered"] > total):
            _problem(p, "inconsistent", "utterances", "more utterances routed or answered than were run")
        elif isinstance(report.get("results"), list) and len(report["results"]) > total:
            _problem(p, "inconsistent", "results", "more results than utterances run")
    return p


def parse_constraints(text):
    """package -> specifier string, from a constraints-<channel>.txt."""
    pins = {}
    for line in (text or "").splitlines():
        line = line.split("#", 1)[0].strip()
        if not line or line.startswith("-") or " @ " in line:
            continue
        m = re.match(r"^\s*([A-Za-z0-9][A-Za-z0-9._-]*)\s*(\[[^\]]*\])?\s*([^;]*)", line)
        if m:
            pins[normalize(m.group(1))] = m.group(3).strip()
    return pins


def _minor(v):
    from packaging.version import InvalidVersion, Version
    try:
        return Version(v).release[:2]
    except InvalidVersion:
        return None


def stale_reasons(report, latest_version, constraints_text, channel_stack=None):
    """Why a well-formed report no longer counts ([] = current).

    "Same channel, loosely" (#6): each core package must be allowed by the
    channel's current constraints AND share major.minor with what the channel
    installs today (`channel_stack`, from the compat run). The second half
    matters on alpha, whose constraints are floors only (ovos-core>=2.2.4a1
    while alpha runs 3.7.x): without it a year-old alpha report would still
    count. On stable the constraints are ranges and the two agree."""
    from packaging.specifiers import InvalidSpecifier, SpecifierSet
    from packaging.version import InvalidVersion, Version
    out = []
    version = (report.get("skill") or {}).get("version")
    if latest_version and version != latest_version:
        _problem(out, "old_version", "skill.version",
                 f"it tested {version}; the current release is {latest_version}")
    if report.get("channel") not in CHANNELS:
        _problem(out, "no_channel", "channel", "the channel is unknown, so it cannot count for one")
        return out
    if constraints_text is None:
        _problem(out, "no_constraints", "channel", f"the {report['channel']} constraints could not be read")
        return out
    pins = parse_constraints(constraints_text)
    stack = {normalize(k): v for k, v in (report.get("stack") or {}).items()}
    for pkg in CORE_PACKAGES:
        have, spec = stack.get(normalize(pkg)), pins.get(normalize(pkg))
        if not have or not spec:
            continue
        try:
            allowed = Version(have) in SpecifierSet(spec, prereleases=True)
        except (InvalidVersion, InvalidSpecifier):
            allowed = False
        if not allowed:
            _problem(out, "old_stack", f"stack.{pkg}",
                     f"{pkg} {have} is no longer allowed on {report['channel']}, which now pins {spec}")
    for pkg in CORE_PACKAGES:
        have = stack.get(normalize(pkg))
        now = {normalize(k): v for k, v in (channel_stack or {}).items()}.get(normalize(pkg))
        if have and now and _minor(have) and _minor(have) != _minor(now) \
                and not any(p["field"] == f"stack.{pkg}" for p in out):
            _problem(out, "old_stack", f"stack.{pkg}",
                     f"{pkg} {have} is an older {report['channel']}: it runs {now} now")
    return out


def counting_problems(report):
    """A well-formed report that cannot count as a pass (it can still count
    as a 'doesn't work' community report, which is the point of those)."""
    out = []
    loaded = report.get("loaded") or {}
    if not loaded.get("ok"):
        _problem(out, "not_loaded", "loaded.ok", "the skill did not load")
    utt = report.get("utterances") or {}
    if report.get("level") == 3 and utt.get("total"):
        if utt.get("routed", 0) / utt["total"] < LEVEL3_RATIO:
            _problem(out, "below_level3", "utterances",
                     f"{utt.get('routed', 0)}/{utt['total']} routed, below the {int(LEVEL3_RATIO * 100)}% level 3 needs")
    return out


def check(report, package=None, latest_version=None, constraints_text=None, channel_stack=None):
    """{"status": "invalid"|"stale"|"current", "passes": bool, "problems": [...]}

    `package` is the store entry's package name (the report must be about
    it); `latest_version` the current release; `constraints_text` the
    report channel's current constraints file; `channel_stack` the core
    versions the channel installs today (package -> version)."""
    problems = structure_problems(report)
    if not problems:
        problems += privacy_problems(report)
        skill_pkg = (report.get("skill") or {}).get("package")
        if package and normalize(skill_pkg) != normalize(package):
            _problem(problems, "wrong_skill", "skill.package",
                     f"the report is about {skill_pkg}, not {package}")
    if problems:
        return {"status": "invalid", "passes": False, "problems": problems}
    stale = stale_reasons(report, latest_version, constraints_text, channel_stack)
    not_passing = counting_problems(report)
    return {"status": "stale" if stale else "current",
            "passes": not not_passing and report.get("outcome", "works") == "works",
            "problems": stale + not_passing}
