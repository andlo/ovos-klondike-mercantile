#!/usr/bin/env python3
"""Level 2 probe: does one installed package load in MiniCroft?

Runs INSIDE the per-package test venv (the channel stack plus the package
under test), so it only imports what that venv has. Writes one JSON object
to --out and always exits 0 when it managed to write it; the outer runner
(run_shard.py) reads the file, not the exit code.

Skills: the skill ids come from the package's own entry points, never from
skill.json (ovos-test-harness found skill.json / repo-name ids drifting from
what the plugin actually registers, and 26 Looks Complete skills have no
skill_id in skill.json at all). One MiniCroft is booted with every language
the skill ships: the first as `lang`, the rest as `secondary_langs`, so a
broken da-dk intent file is caught without one boot per language.

"Loads" means: the skill's loader exists with a live instance after boot.
Registrations are recorded by kind (intents, fallback, common query, OCP,
other) from every bus message carrying the skill's id, because provider
skills (common query, OCP, fallback, common-reading providers) register
with a pipeline instead of registering intents. No registration at all is
a warning, not a failure.

Pipeline plugins: the stage ids come from the package's `opm.pipeline`
entry points and are booted as `extra_pipelines`; get_minicroft raises
when a configured stage fails to load.
"""
import argparse
import json
import os
import re
import sys
import time
import traceback
from importlib.metadata import distribution

SKILL_GROUPS = {"opm.skill", "ovos.plugin.skill", "mycroft.plugin.skill"}
PIPELINE_GROUPS = {"opm.pipeline", "ovos.plugin.pipeline"}


def bcp47(lang):
    parts = lang.replace("_", "-").split("-")
    if len(parts) == 2:
        return f"{parts[0].lower()}-{parts[1].upper()}"
    return lang


def modern_driver():
    """True when ovoscope's get_minicroft takes lang/secondary_langs.

    The test driver is the newest ovoscope whose own declared dependencies
    accept the channel (setup_channel.sh). On alpha that is a current
    ovoscope; on stable (ovos-core 1.3) it is 0.6.0, a thin MiniCroft with
    no language or wait-for-ready options, which boot() fills in the same
    way the modern driver does internally.
    """
    import inspect
    import ovoscope
    # get_minicroft forwards lang/secondary_langs to MiniCroft via **kwargs,
    # so the constructor is where the modern driver declares them.
    params = set(inspect.signature(ovoscope.get_minicroft).parameters)
    params |= set(inspect.signature(ovoscope.MiniCroft.__init__).parameters)
    return "secondary_langs" in params


def takes_extra_pipelines():
    """True when this ovoscope's MiniCroft accepts `extra_pipelines`.

    ovoscope 0.13 (testing) forwards unknown keywords to ovos-core's
    SkillManager, and ovos-core 2.1 raises on `extra_pipelines`. There is no
    need for it there: ovos-core 2.x IntentService loads every installed
    `opm.pipeline` plugin by itself (OVOSPipelineFactory.
    get_installed_pipeline_ids), so the plugin is loaded without it, and the
    probe still checks that it was."""
    import inspect
    import ovoscope
    params = set(inspect.signature(ovoscope.get_minicroft).parameters)
    params |= set(inspect.signature(ovoscope.MiniCroft.__init__).parameters)
    return "extra_pipelines" in params


def boot(ids, langs, max_wait, recorder, extra_pipelines=None, settle=2.0):
    """Boot a MiniCroft with `ids`, recording every bus message from the
    start of skill loading. Returns (croft, driver)."""
    import ovoscope
    if modern_driver():
        base = ovoscope.MiniCroft

        # get_minicroft() constructs and starts the croft itself; skills load
        # in start(), after __init__ built the FakeBus, so subscribing at the
        # end of __init__ sees every registration.
        class RecordingMiniCroft(base):
            def __init__(self, *a, **kw):
                super().__init__(*a, **kw)
                self.bus.on("message", recorder)

        ovoscope.MiniCroft = RecordingMiniCroft
        kwargs = {"lang": langs[0], "secondary_langs": langs[1:], "max_wait": max_wait}
        if extra_pipelines and takes_extra_pipelines():
            kwargs["extra_pipelines"] = extra_pipelines
        croft = ovoscope.get_minicroft(ids, **kwargs)
        time.sleep(settle)
        return croft, f"ovoscope {getattr(ovoscope, '__version__', '') or 'modern'}"

    from ovos_config import Configuration
    from ovos_utils.process_utils import ProcessState
    cfg = Configuration()
    cfg["lang"] = langs[0]
    cfg["secondary_langs"] = langs[1:]
    croft = ovoscope.MiniCroft(ids)
    croft.bus.on("message", recorder)
    croft.start()
    deadline = time.monotonic() + max_wait
    while croft.status.state != ProcessState.READY:
        if time.monotonic() > deadline:
            croft.stop()
            raise TimeoutError(f"MiniCroft did not reach READY in {max_wait}s")
        time.sleep(0.2)
    # The legacy driver does not wait for intent training; give the
    # containers the same kind of bounded settle the modern one applies.
    time.sleep(max(settle, 5.0))
    return croft, "ovoscope legacy (no lang/wait options)"


def intent_service(croft):
    return getattr(croft, "intents", None) or getattr(croft, "intent_service", None)


def entry_points_for(package, groups):
    dist = distribution(package)
    return [ep for ep in dist.entry_points if ep.group in groups], dist.version


LOCALE_FILE = re.compile(
    r"(?:^|/)(?:locale|vocab|dialog|regex)/([a-z]{2,3}(?:[-_][A-Za-z]{2,4})?)/(?:[^/]+/)*[^/]+\.(\w+)$")
INTENT_EXTS = {"intent", "voc", "rx", "entity"}
# Two-letter locale folders (locale/en, locale/ca) are booted as a full tag.
DEFAULT_REGION = {"en": "US", "pt": "PT", "es": "ES", "ca": "ES", "gl": "ES", "eu": "ES",
                  "da": "DK", "sv": "SE", "el": "GR", "fa": "IR", "cs": "CZ", "uk": "UA"}


def full_tag(code):
    code = code.replace("_", "-")
    if "-" in code:
        return bcp47(code)
    return f"{code.lower()}-{DEFAULT_REGION.get(code.lower(), code.upper())}"


def shipped_languages(package):
    """(all languages, languages with intent files) the INSTALLED version ships.

    Not the feed's list: that comes from the repo's current code, while a
    channel may pin an older release (stable tests ovos-skill-wikipedia
    0.8.13, which predates several of its current locales). All languages
    are booted, so a broken dialog file is caught too, but only languages
    that ship intent files (.intent/.voc/.rx/.entity) are expected to
    register intents: a dialog-only translation has nothing to register."""
    langs, intent_langs = set(), set()
    for f in distribution(package).files or []:
        m = LOCALE_FILE.search(str(f).replace("\\", "/"))
        if m:
            tag = full_tag(m.group(1))
            langs.add(tag)
            if m.group(2).lower() in INTENT_EXTS:
                intent_langs.add(tag)
    return sorted(langs), sorted(intent_langs)


def same_language(a, b):
    """en-US == en-us, and a two-letter folder matches its region variants."""
    a, b = a.lower(), b.lower()
    return a == b or a.split("-")[0] == b.split("-")[0] and ("-" not in a or "-" not in b)


def blocked_in_package(package):
    """Where a thread is stuck inside the package's own code, or None.

    Called after a boot timeout. Some skills wait in initialize() for
    things a device provides and MiniCroft does not (network/internet/GUI
    ready signals: ovos-skill-boot-finished loops until they arrive), so the
    load never finishes here although it does on a device. Reported as
    "needs device" with the exact file:line, never as a failure, and never
    silently: the location is shown on the detail page."""
    import traceback as tb
    from pathlib import Path
    dist = distribution(package)
    roots = {str(Path(dist.locate_file(f)).resolve().parent) for f in (dist.files or [])
             if str(f).endswith(".py") and "/" in str(f).replace("\\", "/")}
    for thread_id, frame in sys._current_frames().items():
        stack = tb.extract_stack(frame)
        for fs in reversed(stack):
            if any(str(Path(fs.filename).resolve()).startswith(r) for r in roots):
                return f"{Path(fs.filename).name}:{fs.lineno} in {fs.name}()"
    return None


def classify(msg_type):
    t = msg_type.lower()
    if "register_intent" in t or "intent.register" in t or "register_vocab" in t \
            or "register_entity" in t or "vocab.register" in t:
        return "intents"
    if "fallback" in t and "register" in t:
        return "fallback"
    if t.startswith("ovos.common_reading."):
        return "common_reading"
    if "common_query" in t:
        return "common_query"
    if "common_play" in t or "ocp" in t:
        return "ocp"
    return None


# Status/bookkeeping topics every skill emits; not a registration.
IGNORED_PREFIXES = ("mycroft.skills.", "mycroft.skill.", "enclosure.", "gui.",
                    "ovos.gui.", "skillmanager.", "mycroft.ready", "ovos.skill.",
                    "ovos.skills.settings", "mycroft.gui", "speak", "homescreen.",
                    "ovos.skills.get_skill_settings", "skill.converse")


class Recorder:
    def __init__(self, skill_ids):
        self.skill_ids = set(skill_ids)
        self.kinds = {}
        self.other_types = {}
        self.intents_by_lang = {}

    def owns(self, data, context):
        sid = (context or {}).get("skill_id") or data.get("skill_id")
        if sid in self.skill_ids:
            return True
        name = str(data.get("name") or data.get("intent_name") or "")
        return any(name.startswith(f"{s}:") for s in self.skill_ids)

    def __call__(self, serialized):
        try:
            msg = json.loads(serialized) if isinstance(serialized, str) else serialized
            data = msg.get("data") or {}
            context = msg.get("context") or {}
            mtype = msg.get("type") or ""
        except Exception:
            return
        if not isinstance(data, dict) or not self.owns(data, context):
            return
        kind = classify(mtype)
        if kind is None:
            if mtype.startswith(IGNORED_PREFIXES):
                return
            self.other_types[mtype] = self.other_types.get(mtype, 0) + 1
            return
        self.kinds.setdefault(kind, set())
        name = str(data.get("name") or data.get("intent_name")
                   or data.get("entity_value") or data.get("entity_type") or mtype)
        lang = (data.get("lang") or context.get("lang") or "").lower() or "unknown"
        self.kinds[kind].add((name, lang))
        if kind == "intents":
            self.intents_by_lang.setdefault(lang, set()).add(name)

    def summary(self):
        regs = {k: len(v) for k, v in self.kinds.items()}
        if self.other_types:
            regs["other"] = sorted(self.other_types)
        return regs, {k: len(v) for k, v in sorted(self.intents_by_lang.items())}


def why_not_found(package, skill_id):
    """A skill the plugin manager never handed to MiniCroft: say why."""
    eps = [ep for ep in distribution(package).entry_points
           if ep.group in SKILL_GROUPS and ep.name == skill_id]
    try:
        from ovos_plugin_manager.skills import find_skill_plugins
        found = skill_id in find_skill_plugins()
    except Exception:  # noqa: BLE001
        found = None
    for ep in eps:
        try:
            ep.load()
        except Exception as e:  # noqa: BLE001
            return f"import failed: {type(e).__name__}: {e}"[:400]
    if found is False and eps:
        from importlib.metadata import version as v
        groups = ", ".join(sorted({ep.group for ep in eps}))
        return (f"declared only under entry-point group {groups}, which this channel's "
                f"ovos-plugin-manager {v('ovos-plugin-manager')} does not scan for skills")
    return "skill plugin was not loaded (see log excerpt)"


def loader_state(croft, skill_id, package):
    loader = (getattr(croft, "plugin_skills", {}) or {}).get(skill_id)
    if loader is None:
        return False, why_not_found(package, skill_id)
    instance = getattr(loader, "instance", None)
    loaded = getattr(loader, "loaded", instance is not None)
    if instance is None or not loaded:
        return False, "skill failed to initialise (see log excerpt)"
    return True, None


def probe_skill(args, result):
    eps, version = entry_points_for(args.package, SKILL_GROUPS)
    result["version_installed"] = version
    ids = sorted({ep.name for ep in eps})
    result["plugin_ids"] = ids
    if not ids:
        result.update(status="fail", reason="package declares no skill entry point")
        return
    langs, intent_langs = shipped_languages(args.package)
    result["languages_source"] = "package"
    if args.only_langs:
        langs = [full_tag(l) for l in args.only_langs.split(",") if l]
        intent_langs = [l for l in intent_langs if any(same_language(l, x) for x in langs)]
        result["languages_source"] = "retry"
    if not langs:
        # No recognisable resource folders (unusual layout): boot what the
        # feed read from the repo, but expect nothing per language, since
        # the installed version may not ship those languages.
        langs = [full_tag(l) for l in (args.langs.split(",") if args.langs else []) if l]
        intent_langs = []
        result["languages_source"] = "feed"
    if not langs:
        langs = ["en-US"]
    elif "en-US" in langs:
        langs = ["en-US"] + [l for l in langs if l != "en-US"]
    result["languages_booted"] = langs

    recorder = Recorder(ids)
    try:
        croft, result["driver"] = boot(ids, langs, args.max_wait, recorder, settle=args.settle)
    except TimeoutError as e:
        where = blocked_in_package(args.package)
        if where:
            result.update(status="needs_device",
                          reason=f"load did not finish in MiniCroft: waiting in {where}, "
                                 "likely for something a device provides (network, GUI or "
                                 "other services)")
            return
        raise e
    try:
        failures = []
        for sid in ids:
            ok, why = loader_state(croft, sid, args.package)
            if not ok:
                failures.append(f"{sid}: {why}")
        regs, by_lang = recorder.summary()
        result["registrations"] = regs
        result["intents_by_lang"] = by_lang
        if failures:
            result.update(status="fail", reason="; ".join(failures))
            return
        warnings = []
        if not regs:
            warnings.append("loaded but registered nothing (no intents, fallback or provider)")
        if by_lang:
            missing = [l for l in intent_langs
                       if not any(same_language(l, got) for got in by_lang)]
            if missing:
                result["languages_missing"] = missing
                warnings.append("no intents registered for: " + ", ".join(missing))
        result["warnings"] = warnings
        result["status"] = "pass"
    finally:
        croft.stop()


def probe_pipeline(args, result):
    eps, version = entry_points_for(args.package, PIPELINE_GROUPS)
    result["version_installed"] = version
    ids = sorted({ep.name for ep in eps})
    result["plugin_ids"] = ids
    if not ids:
        result.update(status="fail", reason="package declares no pipeline entry point")
        return
    stages = []
    for ep in eps:
        try:
            cls = ep.load()
        except Exception as e:
            result.update(status="fail", reason=f"{ep.name}: import failed: {e!r}")
            return
        stages.append(f"{ep.name}-high" if hasattr(cls, "match_high") else ep.name)
    result["stages"] = stages
    if not modern_driver():
        # ovos-core 1.3 (stable) builds a fixed list of pipelines and has no
        # loader for third-party pipeline plugins at all ("TODO - replace
        # with plugin loader from OPM" in IntentService). That is the
        # channel's limit, not the plugin's fault, so it is not a failure.
        result.update(status="unsupported",
                      reason="this channel's ovos-core does not load third-party pipeline plugins")
        return
    croft, result["driver"] = boot([], ["en-US"], args.max_wait, lambda _m: None,
                                   extra_pipelines=stages, settle=args.settle)
    try:
        svc = intent_service(croft)
        loaded = set(getattr(svc, "pipeline_plugins", {}) or {})
        missing = [i for i in ids if i not in loaded]
        if missing:
            result.update(status="fail", reason="pipeline did not load: " + ", ".join(missing))
        else:
            result["status"] = "pass"
    finally:
        croft.stop()


def probe_canary(args, result):
    """Boot an empty MiniCroft with two languages: proves the test driver
    works on this channel before any package is blamed for a failure."""
    croft, result["driver"] = boot([], ["en-US", "da-DK"], args.max_wait, lambda _m: None,
                                   settle=0.5)
    croft.stop()
    result["status"] = "pass"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--kind", choices=["skill", "pipeline", "canary"], required=True)
    ap.add_argument("--package", default="")
    ap.add_argument("--langs", default="")
    ap.add_argument("--only-langs", default="", help="boot exactly these languages (per-language retry)")
    ap.add_argument("--out", required=True)
    ap.add_argument("--max-wait", type=float, default=300)
    ap.add_argument("--settle", type=float, default=2.0)
    args = ap.parse_args()

    result = {"kind": args.kind, "package": args.package}
    started = time.monotonic()
    if args.package:
        try:
            result["module_roots"] = sorted({str(f).replace("\\", "/").split("/", 1)[0]
                                             for f in distribution(args.package).files or []
                                             if str(f).endswith(".py") and "/" in str(f).replace("\\", "/")})
        except Exception:  # noqa: BLE001
            pass
    try:
        if args.kind == "skill":
            probe_skill(args, result)
        elif args.kind == "pipeline":
            probe_pipeline(args, result)
        else:
            probe_canary(args, result)
    except BaseException as e:  # noqa: BLE001 - any boot failure is a result
        result.update(status="fail", reason=f"{type(e).__name__}: {e}"[:500])
        traceback.print_exc()
    result["boot_seconds"] = round(time.monotonic() - started, 1)
    with open(args.out, "w") as f:
        json.dump(result, f, indent=2, default=str)
    sys.stdout.flush()
    sys.stderr.flush()
    # MiniCroft leaves non-daemon threads behind on some stacks; the result
    # is written, so do not let them hold the process open until timeout.
    os._exit(0)


if __name__ == "__main__":
    main()
