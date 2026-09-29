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
    return "secondary_langs" in inspect.signature(ovoscope.get_minicroft).parameters


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
        if extra_pipelines:
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


def classify(msg_type):
    t = msg_type.lower()
    if "register_intent" in t or "intent.register" in t or "register_vocab" in t \
            or "register_entity" in t or "vocab.register" in t:
        return "intents"
    if "fallback" in t and "register" in t:
        return "fallback"
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


def loader_state(croft, skill_id):
    loader = (getattr(croft, "plugin_skills", {}) or {}).get(skill_id)
    if loader is None:
        return False, "skill plugin was not loaded (import failed or entry point broken)"
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
    langs = [bcp47(l) for l in (args.langs.split(",") if args.langs else []) if l]
    if not langs:
        langs = ["en-US"]
    elif "en-US" in langs:
        langs = ["en-US"] + [l for l in langs if l != "en-US"]
    result["languages_booted"] = langs

    recorder = Recorder(ids)
    croft, result["driver"] = boot(ids, langs, args.max_wait, recorder, settle=args.settle)
    try:
        failures = []
        for sid in ids:
            ok, why = loader_state(croft, sid)
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
            missing = [l for l in langs if l.lower() not in by_lang]
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
    ap.add_argument("--out", required=True)
    ap.add_argument("--max-wait", type=float, default=300)
    ap.add_argument("--settle", type=float, default=2.0)
    args = ap.parse_args()

    result = {"kind": args.kind, "package": args.package}
    started = time.monotonic()
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
