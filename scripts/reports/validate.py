"""Check an ovos-test-report/1 document (issue #6 maintainer reports, #9
community reports).

The format is defined by the tool that writes it, ovos-tui-client's
headless mode (`ovos-tui --run ... --report FILE|-`, andlo/ovos-tui-client
#51/#54): a `manifest` (channel, installed versions, the tested skills,
routing config, machine), a `summary` and one row per step. It names no
store. One report can cover several skills; Klondike looks at the one it
is about (`view()`), and derives what it needs:

  version / loaded   manifest.skills[<skill id>] (listed = found loaded)
  level              3 when the skill has checked steps, else 2
  routed / checked   its own steps: status "pass" / pass+fail+timeout
  outcome            all passed: works; some: partly; none: doesnt_work
  hardware, langs    manifest.machine.model, manifest.config
  notes              the tester's free text

One implementation of the rules, used by the crawler (maintainer reports
in a skill's repo), the issue workflow (community reports) and the
paste-and-check box (docs/reports.js holds the same rules; tests keep the
two in step). A report is:
  invalid  malformed, inconsistent, or carries private data: never shown
  stale    well-formed, but for an older skill version or a core stack
           the channel no longer runs: shown as history, never counted
  current  counts
Private data is rejected, not scrubbed: the report was meant to be clean
when it left the device, and a store that quietly edits it would publish
something the tester never saw.
"""
import re
from datetime import datetime

SCHEMA = "ovos-test-report/1"
CHANNELS = ("stable", "testing", "alpha")
# "Same channel, loosely" (#6): these must still be allowed by the
# channel's constraints and on the minor the channel installs today.
CORE_PACKAGES = ("ovos-core", "ovos-workshop", "ovos-padatious", "ovos-bus-client",
                 "ovos-plugin-manager")
LEVEL3_RATIO = 0.8
STEP_STATUSES = ("pass", "fail", "timeout", "sent")
CHECKED = ("pass", "fail", "timeout")
MAX_STEPS = 2000

IPV4 = re.compile(r"(?<![\d.])(?:(?:25[0-5]|2[0-4]\d|1?\d?\d)\.){3}(?:25[0-5]|2[0-4]\d|1?\d?\d)(?![\d.])")
EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
HOME = re.compile(r"(?:/home/|/Users/|C:\\Users\\)[^/\\\s]+", re.I)
SECRETISH = re.compile(r"(?i)(?:api[_-]?key|token|secret|password|passwd)\s*[\"':=]+\s*[\"']?[A-Za-z0-9_\-]{8,}")
LONG_TOKEN = re.compile(r"\b[A-Za-z0-9_\-]{40,}\b")
HARMLESS_IPS = ("127.0.0.1", "0.0.0.0")
# Fields that hold version numbers, which look like dotted IP addresses.
VERSION_FIELDS = re.compile(r"^manifest\.(stack\.|skills\.[^.]+\.version$|machine\.python$)")


def normalize(name):
    return re.sub(r"[-_.]+", "-", str(name or "")).lower()


def _problem(problems, code, field, message):
    problems.append({"code": code, "field": field, "message": message})


def _strings(obj, path=""):
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
        if VERSION_FIELDS.match(field):
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
    # OVOS's replies can hold personal data ("14 degrees in <your town>");
    # the tool leaves them out unless asked (--report-replies), for reports
    # the tester keeps. A shared report must not carry them.
    for i, step in enumerate(report.get("steps") or []):
        if isinstance(step, dict) and step.get("replies"):
            _problem(out, "private_replies", f"steps[{i}].replies",
                     "contains OVOS's replies; share a report made without --report-replies")
            break
    return out


def _is_int(x):
    return isinstance(x, int) and not isinstance(x, bool) and x >= 0


def structure_problems(report):
    """Shape and internal consistency. Hand-written rather than a JSON Schema
    library, so the browser applies the very same rules without one."""
    p = []
    if not isinstance(report, dict):
        _problem(p, "type", "", "the report is not a JSON object")
        return p
    if report.get("schema") != SCHEMA:
        _problem(p, "schema", "schema", f"'schema' must be \"{SCHEMA}\"")
    m = report.get("manifest")
    if not isinstance(m, dict):
        _problem(p, "missing", "manifest", "'manifest' is missing")
        return p
    if not isinstance(m.get("tool"), str):
        _problem(p, "missing", "manifest.tool", "'manifest.tool' is missing")
    created = m.get("created_at")
    try:
        datetime.fromisoformat(str(created).replace("Z", "+00:00"))
    except ValueError:
        _problem(p, "type", "manifest.created_at", "'manifest.created_at' is not an ISO date-time")
    if m.get("channel") is not None and not isinstance(m.get("channel"), str):
        _problem(p, "type", "manifest.channel", "'manifest.channel' must be a channel name or null")
    if not isinstance(m.get("stack"), dict):
        _problem(p, "type", "manifest.stack", "'manifest.stack' must be an object")
    skills = m.get("skills")
    if not isinstance(skills, dict) or not skills:
        _problem(p, "missing", "manifest.skills", "'manifest.skills' must name the tested skills")
    elif not all(isinstance(v, dict) for v in skills.values()):
        _problem(p, "type", "manifest.skills", "every entry of 'manifest.skills' must be an object")
    steps = report.get("steps")
    if not isinstance(steps, list) or len(steps) > MAX_STEPS:
        _problem(p, "type", "steps", f"'steps' must be a list of at most {MAX_STEPS} rows")
        return p
    for i, s in enumerate(steps):
        if not isinstance(s, dict) or not isinstance(s.get("utterance"), str) \
                or s.get("status") not in STEP_STATUSES:
            _problem(p, "type", f"steps[{i}]", "each step needs 'utterance' and a known 'status'")
            return p
    summary = report.get("summary")
    if not isinstance(summary, dict):
        _problem(p, "missing", "summary", "'summary' is missing")
        return p
    counted = {"passed": "pass", "failed": "fail", "timed_out": "timeout"}
    for key, status in counted.items():
        n = sum(1 for s in steps if s["status"] == status)
        if _is_int(summary.get(key)) and summary[key] != n:
            _problem(p, "inconsistent", f"summary.{key}", f"'summary.{key}' says {summary[key]}, the steps say {n}")
    if _is_int(summary.get("steps")) and summary["steps"] != len(steps):
        _problem(p, "inconsistent", "summary.steps", "'summary.steps' does not match the steps")
    return p


def skill_id_for(report, package):
    """The tested skill id whose package is `package`, or None."""
    for sid, info in ((report.get("manifest") or {}).get("skills") or {}).items():
        if isinstance(info, dict) and normalize(info.get("package")) == normalize(package):
            return sid
    return None


def view(report, skill_id):
    """What Klondike reads for one skill of the report."""
    m = report.get("manifest") or {}
    info = (m.get("skills") or {}).get(skill_id) or {}
    own = [s for s in report.get("steps") or []
           if isinstance(s.get("expected"), str) and (s["expected"] == skill_id or s["expected"].startswith(f"{skill_id}:"))]
    checked = [s for s in own if s.get("status") in CHECKED]
    routed = sum(1 for s in checked if s["status"] == "pass")
    if not checked:
        outcome = "works"
    elif routed == len(checked):
        outcome = "works"
    elif routed:
        outcome = "partly"
    else:
        outcome = "doesnt_work"
    cfg = m.get("config") or {}
    langs = [x for x in [cfg.get("lang") or m.get("lang")] + list(cfg.get("secondary_langs") or []) if x]
    return {
        "skill_id": skill_id, "package": info.get("package"), "version": info.get("version"),
        "loaded": info.get("active") is not False,
        "level": 3 if checked else 2, "checked": len(checked), "routed": routed,
        "answered": sum(1 for s in own if s.get("answered")),
        "outcome": outcome, "channel": m.get("channel"),
        "created_at": m.get("created_at"), "tool": m.get("tool"),
        "hardware": (m.get("machine") or {}).get("model") or (m.get("machine") or {}).get("arch") or "",
        "languages": langs[:10], "notes": (report.get("notes") or "")[:1000] if isinstance(report.get("notes"), str) else "",
    }


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


def stale_reasons(report, v, latest_version, constraints_text, channel_stack=None):
    """Why a well-formed report no longer counts ([] = current).

    Core packages must be allowed by the channel's current constraints AND
    share major.minor with what the channel installs today (`channel_stack`,
    from the compat run). The second half matters on alpha, whose
    constraints are floors only (ovos-core>=2.2.4a1 while alpha runs 3.7.x):
    without it a year-old alpha report would still count."""
    from packaging.specifiers import InvalidSpecifier, SpecifierSet
    from packaging.version import InvalidVersion, Version
    out = []
    channel = v["channel"]
    if latest_version and v["version"] != latest_version:
        _problem(out, "old_version", "manifest.skills",
                 f"it tested {v['version']}; the current release is {latest_version}")
    if channel not in CHANNELS:
        _problem(out, "no_channel", "manifest.channel",
                 "the channel is unknown (run the tool with --channel), so it cannot count for one")
        return out
    stack = {normalize(k): val for k, val in ((report.get("manifest") or {}).get("stack") or {}).items()}
    if not stack.get("ovos-core"):
        _problem(out, "no_stack", "manifest.stack",
                 "the report has no installed versions (run the tool on the device itself)")
        return out
    if constraints_text is None:
        _problem(out, "no_constraints", "manifest.channel", f"the {channel} constraints could not be read")
        return out
    pins = parse_constraints(constraints_text)
    now = {normalize(k): val for k, val in (channel_stack or {}).items()}
    for pkg in CORE_PACKAGES:
        have, spec = stack.get(normalize(pkg)), pins.get(normalize(pkg))
        if not have:
            continue
        if spec:
            try:
                allowed = Version(have) in SpecifierSet(spec, prereleases=True)
            except (InvalidVersion, InvalidSpecifier):
                allowed = False
            if not allowed:
                _problem(out, "old_stack", f"manifest.stack.{pkg}",
                         f"{pkg} {have} is no longer allowed on {channel}, which now pins {spec}")
                continue
        cur = now.get(normalize(pkg))
        if cur and _minor(have) and _minor(have) != _minor(cur):
            _problem(out, "old_stack", f"manifest.stack.{pkg}",
                     f"{pkg} {have} is an older {channel}: it runs {cur} now")
    return out


def counting_problems(v):
    """A well-formed report that cannot count as a pass (it can still count
    as a "doesn't work" community report, which is the point of those)."""
    out = []
    if not v["loaded"]:
        _problem(out, "not_loaded", "manifest.skills", "the skill was not active")
    if v["checked"] and v["routed"] / v["checked"] < LEVEL3_RATIO:
        _problem(out, "below_level3", "steps",
                 f"{v['routed']}/{v['checked']} reached it, below the {int(LEVEL3_RATIO * 100)}% level 3 needs")
    return out


def check(report, package=None, latest_version=None, constraints_text=None, channel_stack=None):
    """{"status": "invalid"|"stale"|"current", "passes": bool,
        "problems": [...], "view": {...} or None}

    `package` is the store entry's package name (the report must cover it);
    `latest_version` the current release; `constraints_text` the report
    channel's current constraints file; `channel_stack` the core versions
    the channel installs today (package -> version)."""
    problems = structure_problems(report)
    v = None
    if not problems:
        problems += privacy_problems(report)
        sid = skill_id_for(report, package) if package else next(iter(report["manifest"]["skills"]))
        if sid is None:
            tested = ", ".join(str((i or {}).get("package")) for i in report["manifest"]["skills"].values())
            _problem(problems, "wrong_skill", "manifest.skills", f"the report tested {tested}, not {package}")
        else:
            v = view(report, sid)
            if not v["version"]:
                _problem(problems, "missing", "manifest.skills",
                         "the report has no version for the skill (run the tool on the device itself)")
    if problems:
        return {"status": "invalid", "passes": False, "problems": problems, "view": v}
    stale = stale_reasons(report, v, latest_version, constraints_text, channel_stack)
    not_passing = counting_problems(v)
    return {"status": "stale" if stale else "current",
            "passes": not not_passing and v["outcome"] == "works",
            "problems": stale + not_passing, "view": v}
