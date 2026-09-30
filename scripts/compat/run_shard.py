#!/usr/bin/env python3
"""Test a shard of packages against one channel: level 1 (installs) and
level 2 (loads in MiniCroft).

Runs in the secret-less test job. Input is a JSON list of items from
plan.py; output is one JSON list of result records. Every package gets a
fresh copy of the channel base venv, so one skill's dependencies can never
change what the next skill is tested against.

Result status:
  pass   the level was reached
  unsupported  the channel cannot run this kind of package at all (stable's
         ovos-core has no third-party pipeline plugin loader): not the
         package's fault, shown as "not supported", never as a failure
  needs_device  loading blocks in the package's own code waiting for
         something only a device provides (network/GUI ready signals);
         shown as "needs device" with the file:line, never as a failure
  needs_config  its own load error says it needs configuration first (an
         API key, account or identity): "needs config", with the message
  fail   the package's own fault (dependency conflict, import error, boot
         error, timeout while booting)
  error  our/infra fault (PyPI unreachable, disk full): not published as a
         failure, and retried on the next run
"""
import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
PROBE = HERE / "probe.py"
ANSI = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")
NETWORK_ERRORS = re.compile(
    r"(ConnectionError|ReadTimeout|Max retries exceeded|Temporary failure in name "
    r"resolution|No space left on device|HTTP error 5\d\d|403 Client Error)")
MAX_EXCERPT = 4000

# "Needs config" (issue #6): a package that cannot start until the user
# configures it (API key, account, identity) is not broken. Only the
# package's OWN load error is matched (a pipeline load error naming one of
# its ids, or a traceback running through its own modules), and only
# against phrases that say something is missing or unset, so a real bug
# stays a failure.
NEEDS_CONFIG = re.compile(
    r"(api[ _-]?key|token|credential|password|secret|identity|account|"
    r"not (?:set|configured)|please (?:pass|set|configure)|missing (?:config|setting)|"
    r"no .* configured)", re.I)
EXC_LINE = re.compile(r"^(?:\w+\.)*\w*(?:Error|Exception): (?P<msg>.+)$")


def config_message(output, plugin_ids, module_roots):
    """The package's own load error when it says configuration is missing."""
    text = ANSI.sub("", output or "")
    for pid in plugin_ids or []:
        m = re.search(rf"Failed to load pipeline plugin '{re.escape(pid)}': (?P<msg>.+)$", text, re.M)
        if m and NEEDS_CONFIG.search(m.group("msg")):
            return m.group("msg").strip()[:300]
    markers = [f"/site-packages/{r}/" for r in module_roots or []]
    for block in text.split("Traceback (most recent call last)")[1:]:
        lines = block.splitlines()
        if not any(any(mk in l for mk in markers) for l in lines):
            continue
        for l in lines:
            m = EXC_LINE.match(l.strip())
            if m and NEEDS_CONFIG.search(m.group("msg")):
                return m.group("msg").strip()[:300]
    return None


def excerpt(text, anchor_patterns=("Traceback (most recent call last)", "ERROR", "error:")):
    """The most useful tail of a log: from the last traceback/error on."""
    text = ANSI.sub("", text or "")
    lines = text.splitlines()
    start = max(0, len(lines) - 40)
    for i in range(len(lines) - 1, -1, -1):
        if any(p in lines[i] for p in anchor_patterns):
            start = max(0, i - 5)
            break
    out = "\n".join(lines[start:start + 60])
    return out[-MAX_EXCERPT:]


def pip_reason(output):
    """One line saying WHY pip gave up, e.g. "neon-skill-about 1.0.4 depends
    on ovos-workshop~=0.0; channel pins ovos-workshop<3.5.0,>=3.4.0"."""
    lines = [l.strip() for l in ANSI.sub("", output).splitlines()]
    if "The conflict is caused by:" in lines:
        i = lines.index("The conflict is caused by:")
        block = []
        for l in lines[i + 1:]:
            if not l or l.startswith(("Additionally", "To fix")):
                break
            block.append(l.replace("The user requested (constraint)", "channel pins"))
        if block:
            return "; ".join(dict.fromkeys(block))[:500]
    for pat in ("Failed to build", "No matching distribution found", "Could not find a version",
                "Cannot install", "subprocess-exited-with-error"):
        for l in lines:
            if pat in l:
                return l.removeprefix("ERROR: ")[:300]
    return "pip install failed"


def install_excerpt(output):
    text = ANSI.sub("", output)
    for anchor in ("The conflict is caused by:", "Getting requirements to build wheel", "ERROR:"):
        i = text.find(anchor)
        if i >= 0:
            return text[max(0, i - 400):][:MAX_EXCERPT]
    return excerpt(output)


# Intent training. ovoscope's defaults (180s of silence, 600s in total)
# suit a single-language CI boot; a skill booted with ~20 languages trains
# ~20 padatious containers, which took 220s alone on 8 cores and over 600s
# under load (ovos-skill-alerts). A hosted runner has 2 cores. Training that
# still has not finished after this is reported as a failure.
TRAINED_TIMEOUT = 600
TRAINED_MAX = 1800
PROBE_ENV = {"PIP_NO_INPUT": "1", "OVOSCOPE_TRAINED_TIMEOUT": str(TRAINED_TIMEOUT),
             "OVOSCOPE_TRAINED_MAX": str(TRAINED_MAX)}


def run(cmd, timeout, log_path):
    with open(log_path, "w") as log:
        try:
            proc = subprocess.run(cmd, stdout=log, stderr=subprocess.STDOUT,
                                  timeout=timeout, env={**os.environ, **PROBE_ENV})
            rc = proc.returncode
        except subprocess.TimeoutExpired:
            rc = None
    return rc, Path(log_path).read_text(errors="replace")


def test_item(item, args, workroot):
    started = time.monotonic()
    rec = {
        "id": item["id"], "channel": args.channel, "key": item["key"],
        "kind": item["kind"], "package": item["package"],
        "requested_version": item.get("version"), "channel_pinned": item.get("channel_pinned", False),
        "tested_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "level": 0,
    }
    venv = Path(workroot) / "venv"
    if venv.exists():
        shutil.rmtree(venv)
    try:
        shutil.copytree(args.base_venv, venv, symlinks=True)
    except OSError as e:
        rec.update(status="error", stage="setup", reason=f"could not copy base venv: {e}")
        return rec
    py = str(venv / "bin" / "python")
    try:
        # Level 1. A channel that pins the package decides its version (what
        # a device on that channel actually runs); otherwise the latest
        # release, still under the channel constraints.
        spec = item["package"] if item.get("channel_pinned") or not item.get("version") \
            else f"{item['package']}=={item['version']}"
        rc, out = run([py, "-m", "pip", "install", "--disable-pip-version-check",
                       "-c", args.constraints, spec],
                      args.install_timeout, Path(workroot) / "install.log")
        if rc != 0:
            if rc is None:
                rec.update(status="error", stage="install",
                           reason=f"pip install timed out after {args.install_timeout}s")
            elif NETWORK_ERRORS.search(out):
                rec.update(status="error", stage="install", reason="network error during pip install")
            else:
                rec.update(status="fail", stage="install", reason=pip_reason(out))
            rec["log_excerpt"] = install_excerpt(out)
            return rec
        rec["level"] = 1

        # Level 2
        def probe_once(only_langs=""):
            result_path = Path(workroot) / "probe.json"
            if result_path.exists():
                result_path.unlink()
            cmd = [py, str(PROBE), "--kind", item["kind"], "--package", item["package"],
                   "--langs", ",".join(item.get("languages") or []),
                   "--out", str(result_path), "--max-wait", str(args.boot_timeout)]
            if only_langs:
                cmd += ["--only-langs", only_langs]
            rc, out = run(cmd, args.boot_timeout + TRAINED_MAX + 120, Path(workroot) / "probe.log")
            if not result_path.exists():
                reason = (f"timed out booting after {args.boot_timeout + TRAINED_MAX + 120}s" if rc is None
                          else f"probe crashed (exit {rc})")
                return {"status": "fail", "reason": reason}, out
            return json.loads(result_path.read_text()), out

        probe, out = probe_once()
        booted = probe.get("languages_booted") or []
        if (item["kind"] == "skill" and probe.get("status") == "fail" and len(booted) > 1
                and "failed to initialise" in (probe.get("reason") or "")):
            # A skill that fails with ALL its languages configured may only
            # be broken in one of them (ovos-skill-spelling 0.2.6: a bad
            # ro-ro regex). A device only loads its own languages, so that
            # is a per-language defect, not "doesn't load". Retry with the
            # primary language alone; if that loads, try each other
            # language alone to name the broken ones.
            primary, primary_out = probe_once(booted[0])
            if primary.get("status") == "pass":
                failing, by_lang = [], dict(primary.get("intents_by_lang") or {})
                for lang in booted[1:]:
                    one, _ = probe_once(lang)
                    if one.get("status") == "pass":
                        by_lang.update(one.get("intents_by_lang") or {})
                    else:
                        failing.append(lang)
                if failing:
                    primary["languages_booted"] = booted
                    primary["intents_by_lang"] = dict(sorted(by_lang.items()))
                    primary["languages_missing"] = failing
                    primary["warnings"] = [
                        "fails to load when these languages are configured: " + ", ".join(failing)
                        + " (loads with the others; see log excerpt)"]
                    probe, out = primary, out  # keep the multi-language failure log
                else:
                    # Every language loads on its own: the failure only happens
                    # in combination, which a device with all of them would hit.
                    probe["reason"] += " (each language loads on its own; fails only in combination)"

        rec["version_tested"] = probe.get("version_installed")
        for k in ("plugin_ids", "registrations", "intents_by_lang", "languages_booted",
                  "languages_missing", "warnings", "stages", "boot_seconds", "driver"):
            if probe.get(k) not in (None, [], {}):
                rec[k] = probe[k]
        if probe.get("status") in ("unsupported", "needs_device"):
            rec.update(status=probe["status"], stage="load", reason=probe.get("reason", ""),
                       log_excerpt=excerpt(out))
        elif probe.get("status") == "pass":
            rec.update(status="pass", stage="load", level=2)
            if rec.get("warnings"):
                rec["log_excerpt"] = excerpt(out)
        else:
            cfg = config_message(out, probe.get("plugin_ids"), probe.get("module_roots"))
            if cfg:
                rec.update(status="needs_config", stage="load",
                           reason=f"needs configuration before it can load: {cfg}",
                           log_excerpt=excerpt(out))
            else:
                rec.update(status="fail", stage="load", reason=probe.get("reason", "did not load"),
                           log_excerpt=excerpt(out))
        return rec
    finally:
        rec["duration_seconds"] = round(time.monotonic() - started, 1)
        shutil.rmtree(venv, ignore_errors=True)


ROUTE = HERE / "route.py"
from feed import LEVEL3_RATIO  # noqa: E402
# Languages routed per shard. Golden files often cover 15-25 languages and
# every language is a boot of its own with the whole baseline training
# (see route.py), so a shard routes en-US plus the languages most of its
# skills have rows for, and lists the rest as not tested.
ROUTE_MAX_LANGS = int(os.environ.get("COMPAT_ROUTE_MAX_LANGS", "4"))
# Minutes of level 3 routing per shard, all languages together (issue #15):
# one skill with big multi-language golden files must not hold the whole
# run. Rows past it are left out and the language is marked partial;
# languages not started are listed as not routed.
ROUTE_BUDGET_MIN = float(os.environ.get("COMPAT_ROUTE_BUDGET_MIN", "30"))
# The Klondike job (one per channel, issue #13): its routing budget, and how
# long one boot may take. The profile alone is ~45 skills to train (835 s
# locally for en-US, alpha), with every tested skill loaded next to it.
KLONDIKE_BUDGET_MIN = float(os.environ.get("COMPAT_KLONDIKE_BUDGET_MIN", "240"))
KLONDIKE_BOOT_TIMEOUT = int(os.environ.get("COMPAT_KLONDIKE_BOOT_TIMEOUT", "3000"))
# Generated rows are drafted in English only for now: ovoscope generate's
# default slot values are English-only (ovoscope#224), so other languages
# skip most templates.
GENERATED_LANGS = ["en-us"]


def lang_key(lang):
    parts = lang.replace("_", "-").split("-")
    return parts[0].lower() + ("-" + parts[1].upper() if len(parts) > 1 else "")


def prepare_rows(item, rec, args, workroot):
    """Checkout at the tested version's tag, golden files, generated rows.
    Returns {"golden": [files], "generated": [files]} and fills rec["routing"]."""
    from rows import checkout, golden_files
    import generated
    routing = rec.setdefault("routing", {})
    runs = {}
    version = rec.get("version_tested") or item.get("version")
    src = Path(workroot) / "src" / item["id"]
    tag, why = checkout(item["repo"], version, src) if item.get("repo") else (None, "no repository")
    routing["ref"] = tag
    if not tag:
        routing["golden"] = {"status": "none", "reason": why}
        routing["generated"] = {"status": "none", "reason": why}
        return runs
    files = golden_files(src)
    if files:
        runs["golden"] = files
    else:
        routing["golden"] = {"status": "none", "reason": f"no test/end2end/golden_utterances*.jsonl at {tag}"}
    gen_out = Path(workroot) / "gen" / f"{item['id']}.jsonl"
    gen_out.parent.mkdir(parents=True, exist_ok=True)
    skill_id = (rec.get("plugin_ids") or [None])[0]
    g = generated.generate(args.generator, skill_id, src, GENERATED_LANGS, gen_out) if skill_id \
        else {"status": "none", "reason": "no skill id"}
    if g["status"] == "ok":
        runs["generated"] = [str(gen_out)]
    routing["generated"] = {k: v for k, v in g.items() if k in ("status", "reason")}
    return runs


def build_route_venv(args, workroot, candidates, requirements, name="route-venv",
                     label="the default skills"):
    """Base venv + a baseline's requirements + the shard's skills.
    Returns (python, {id: reason} for skills that would not install here, freeze)."""
    venv = Path(workroot) / name
    if venv.exists():
        shutil.rmtree(venv)
    shutil.copytree(args.base_venv, venv, symlinks=True)
    py = str(venv / "bin" / "python")
    base_cmd = [py, "-m", "pip", "install", "--disable-pip-version-check", "-c", args.constraints]
    rc, out = run(base_cmd + list(requirements), args.install_timeout, Path(workroot) / f"{name}-baseline.log")
    if rc != 0:
        raise RuntimeError(f"{label} did not install under the channel constraints: "
                           + (pip_reason(out) if rc is not None else "timed out"))
    refused = {}
    for item, rec in candidates:
        spec = item["package"] if item.get("channel_pinned") else f"{item['package']}=={rec['version_tested']}"
        rc, out = run(base_cmd + [spec], args.install_timeout, Path(workroot) / f"{name}-install.log")
        if rc != 0:
            refused[item["id"]] = (f"does not install next to {label}: "
                                   + (pip_reason(out) if rc is not None else "timed out"))
    freeze = subprocess.run([py, "-m", "pip", "freeze", "--disable-pip-version-check"],
                            capture_output=True, text=True).stdout
    return py, refused, freeze


def pick_langs(all_runs):
    counts = {}
    for runs in all_runs.values():
        langs = set()
        for run, files in runs.items():
            if run == "generated":
                langs |= {lang_key(l) for l in GENERATED_LANGS}
                continue
            for f in files:
                name = Path(f).stem.replace("golden_utterances", "").lstrip("_-")
                if name:
                    langs.add(lang_key(name))
                else:
                    for line in Path(f).read_text(encoding="utf-8", errors="replace").splitlines()[:50]:
                        try:
                            langs.add(lang_key(json.loads(line)["lang"]))
                        except Exception:  # noqa: BLE001
                            pass
        for l in langs:
            counts[l] = counts.get(l, 0) + 1
    ordered = sorted(counts, key=lambda l: (l != "en-US", -counts[l], l))
    return ordered[:ROUTE_MAX_LANGS], ordered[ROUTE_MAX_LANGS:]


def prepare_shard(items, results, args, workroot):
    """(skills of the shard that loaded at level 2 and have rows, their rows).
    The rows are fetched once and routed against every baseline."""
    by_id = {r["id"]: r for r in results}
    candidates = [(i, by_id[i["id"]]) for i in items
                  if i.get("route_key") and i["kind"] == "skill" and i["id"] in by_id
                  and by_id[i["id"]].get("status") == "pass" and by_id[i["id"]].get("plugin_ids")]
    all_runs = {}
    for item, rec in candidates:
        rec["route_key"] = item["route_key"]
        try:
            all_runs[item["id"]] = prepare_rows(item, rec, args, workroot)
        except Exception as e:  # noqa: BLE001
            rec.setdefault("routing", {})["error"] = f"could not fetch rows: {e}"[:300]
    return [(i, r) for i, r in candidates if all_runs.get(i["id"])], all_runs


BOOT_FIELDS = ("lang", "status", "reason", "driver", "pipeline", "pipeline_dropped", "baseline_ids",
               "not_loaded", "boot_seconds", "seconds", "log_excerpt", "questions_not_released",
               "row_seconds", "budget_skipped")


def route_pass(routable, all_runs, spec, field, args, workroot, deadline, label, budget_min):
    """Route the shard's rows against one baseline (spec: requirements,
    pipeline, exclude_ids); counts go to rec[field]. Level 3 is only set
    from the normal-install pass (field "routing")."""
    if field != "routing":
        for _, rec in routable:
            base = rec.get("routing") or {}
            rec[field] = {k: v for k, v in base.items() if k == "ref"}
            for run in ("golden", "generated"):
                if (base.get(run) or {}).get("status") in ("none", "unavailable", "error"):
                    rec[field][run] = dict(base[run])
    try:
        py, refused, freeze = build_route_venv(args, workroot, routable, spec["requirements"],
                                               f"{field}-venv", label)
    except Exception as e:  # noqa: BLE001
        for _, rec in routable:
            rec[field]["error"] = str(e)[:300]
        return None
    for item, rec in routable:
        if item["id"] in refused:
            rec[field]["install"] = refused[item["id"]]
    routable = [(i, r) for i, r in routable if i["id"] not in refused]
    langs, skipped = pick_langs({i["id"]: all_runs[i["id"]] for i, _ in routable})
    manifest = {"pipeline": spec.get("pipeline") or [], "exclude_ids": spec.get("exclude_ids") or [],
                "items": [{"id": i["id"], "skill_ids": r["plugin_ids"], "runs": all_runs[i["id"]]}
                          for i, r in routable]}
    boots = run_boots(py, manifest, langs, skipped, field, args, workroot,
                      min(deadline, time.monotonic() + budget_min * 60))
    aggregate(routable, boots, langs, skipped, field)
    shutil.rmtree(Path(workroot) / f"{field}-venv", ignore_errors=True)  # disk: one venv at a time
    return {"langs": langs, "langs_skipped": skipped, "freeze": freeze,
            "excluded_ids": spec.get("exclude_ids") or [],
            "boots": [{k: b.get(k) for k in BOOT_FIELDS} for b in boots]}


def run_boots(py, manifest, langs, skipped, prefix, args, workroot, deadline, boot_timeout=None):
    """One route.py process per language, in turn, until `deadline`."""
    boot_timeout = boot_timeout or args.boot_timeout
    man_path = Path(workroot) / f"{prefix}-manifest.json"
    man_path.write_text(json.dumps(manifest))
    n_rows = sum(len(Path(f).read_text(encoding="utf-8", errors="replace").splitlines())
                 for runs in manifest["items"] for fs in runs["runs"].values() for f in fs)
    boots = []
    last_boot = 0.0
    for lang in langs:
        # A language is only started when what is left can pay for its boot
        # (as long as the last one took) and some rows: on the runners a
        # boot with every baseline skill trained takes 7-10 minutes, and a
        # boot that the budget ends before its first row is time for nothing.
        left = deadline - time.monotonic()
        if left < last_boot + 120:
            skipped.insert(0, lang)
            print(f"    {prefix} {lang}: skipped, out of time", flush=True)
            continue
        out_path = Path(workroot) / f"{prefix}-{lang}.json"
        budget = int(min(boot_timeout + TRAINED_MAX + n_rows * (args.route_timeout + 2) + 300,
                         max(600, left)))
        # route.py stops itself between rows at --budget; that has to come
        # well before this process timeout (one row can take --timeout), or
        # the timeout kills it first and the language reads as timed out.
        rc, log = run([py, str(ROUTE), "--manifest", str(man_path), "--lang", lang,
                       "--out", str(out_path), "--max-wait", str(boot_timeout),
                       "--timeout", str(args.route_timeout),
                       "--budget", str(int(max(60, min(budget, left) - args.route_timeout - 75)))],
                      budget, Path(workroot) / f"{prefix}-{lang}.log")
        try:
            res = json.loads(out_path.read_text())
        except (OSError, ValueError):
            res = {"lang": lang, "status": "boot_failed",
                   "reason": "route probe timed out" if rc is None else f"route probe crashed (exit {rc})"}
        if res.get("status") == "running":
            # The probe died or was killed after writing some rows: keep
            # what it measured, say why the rest is missing. Only a timeout
            # blames the row in flight (route.py already bounds each
            # utterance, so this is the last-resort path).
            cur = res.pop("current", None)
            if rc is None and cur:
                r = res.setdefault("results", {}).setdefault(cur["id"], {}).setdefault(cur["run"], {"total": 0})
                r["hang"] = r.get("hang", 0) + 1
                r.setdefault("misses", []).append({"utterance": cur["utterance"], "kind": "hang"})
            res["status"] = "partial" if res.get("results") else "boot_failed"
            res["reason"] = ("route probe timed out" if rc is None else f"route probe exited ({rc})") \
                + "; later rows not run"
        if res.get("status") != "ok":
            res["log_excerpt"] = excerpt(log)
        print(f"    {prefix} {lang}: {res.get('status')} {res.get('reason', '')} "
              f"boot={res.get('boot_seconds')}s total={res.get('seconds')}s "
              f"rows={res.get('row_seconds')}", flush=True)
        boots.append(res)
        if isinstance(res.get("boot_seconds"), (int, float)):
            last_boot = max(last_boot, res["boot_seconds"])
    return boots


LIST_PLUGINS = """
import json
from importlib.metadata import distributions
out = []
for d in distributions():
    for ep in d.entry_points:
        # The same groups probe.py reads (SKILL_GROUPS): current skills use
        # opm.skill, older ones ovos.plugin.skill or mycroft.plugin.skill.
        if ep.group in ("opm.skill", "ovos.plugin.skill", "mycroft.plugin.skill"):
            out.append({"skill_id": ep.name, "dist": d.metadata["Name"], "version": d.version})
print(json.dumps(out))
"""


def normalize(name):
    return re.sub(r"[-_.]+", "-", name).lower()


def install_items(py, args, workroot, candidates, label):
    """Install the tested skills into a venv that already has a baseline.
    Returns {id: reason} for those that would not install next to it."""
    base_cmd = [py, "-m", "pip", "install", "--disable-pip-version-check", "-c", args.constraints]
    refused = {}
    for item, rec in candidates:
        spec = item["package"] if item.get("channel_pinned") else f"{item['package']}=={rec['version_tested']}"
        rc, out = run(base_cmd + [spec], args.install_timeout, Path(workroot) / "klondike-install.log")
        if rc != 0:
            refused[item["id"]] = (f"does not install next to {label}: "
                                   + (pip_reason(out) if rc is not None else "timed out"))
    return refused


def list_skills(py):
    listed = subprocess.run([py, "-c", LIST_PLUGINS], capture_output=True, text=True)
    return json.loads(listed.stdout)


def klondike_job(args, workroot, deadline):
    """Level 3 against the Klondike profile (issue #13): one job per channel,
    so the profile (~45 skills to train) is booted once per language rather
    than once per shard. In that one core per language:
      * the profile's own store skills, with their rows: the profile against
        itself; a sentence another profile skill takes is a collision;
      * every other skill that passed level 2 on the channel, with its rows:
        each skill against the profile. A sentence a profile skill takes
        counts (a device with the profile would see it); one taken by
        another tested skill does not (two alternatives outside the profile
        are never tested against each other, as intended).
    Which skills are in the profile is read from the venv after the profile
    alone is installed, so ovos-core[...] never needs expanding by hand."""
    spec = args.klondike
    try:
        py, _, _ = build_route_venv(args, workroot, [], spec["requirements"], "klondike-venv",
                                    "the Klondike profile")
        profile_skills = list_skills(py)
    except Exception as e:  # noqa: BLE001 - a resolution failure is a finding in itself
        return {"error": str(e)[:500]}
    fmap, exclude = spec.get("feed_map") or {}, set(spec.get("exclude_ids") or [])
    profile_ids = {s["skill_id"] for s in profile_skills} - exclude
    entries, not_store = [], []
    for inst in sorted(profile_skills, key=lambda x: x["skill_id"]):
        if inst["skill_id"] in exclude:
            continue
        entry = fmap.get(normalize(inst["dist"]))
        if not entry or not entry.get("repo"):
            not_store.append(inst["skill_id"])
            continue
        entries.append(({"id": entry["id"], "repo": entry["repo"], "version": inst["version"], "kind": "skill"},
                        {"id": entry["id"], "version_tested": inst["version"],
                         "plugin_ids": [inst["skill_id"]], "package": inst["dist"], "member": True}))
    member_entry_ids = {i["id"] for i, _ in entries}
    tested = [i for i in spec.get("items") or []
              if i["id"] not in member_entry_ids and not set(i.get("plugin_ids") or []) & profile_ids]
    candidates = [(i, {"id": i["id"], "version_tested": i["version"], "plugin_ids": i["plugin_ids"],
                       "package": i["package"], "member": False}) for i in tested]
    refused = install_items(py, args, workroot, candidates, "the Klondike profile")
    entries += [(i, r) for i, r in candidates if i["id"] not in refused]
    freeze = subprocess.run([py, "-m", "pip", "freeze", "--disable-pip-version-check"],
                            capture_output=True, text=True).stdout
    all_runs = {}
    for item, rec in entries:
        try:
            runs = prepare_rows(item, rec, args, workroot)
        except Exception as e:  # noqa: BLE001
            rec.setdefault("routing", {})["error"] = f"could not fetch rows: {e}"[:300]
            runs = {}
        if runs:
            all_runs[item["id"]] = runs
    routable = [(i, r) for i, r in entries if all_runs.get(i["id"])]
    langs, skipped = pick_langs({i["id"]: all_runs[i["id"]] for i, _ in routable})
    manifest = {"pipeline": spec.get("pipeline") or [], "exclude_ids": sorted(exclude),
                "counted_ids": sorted(profile_ids),
                "items": [{"id": i["id"], "skill_ids": r["plugin_ids"], "runs": all_runs[i["id"]]}
                          for i, r in routable]}
    boots = run_boots(py, manifest, langs, skipped, "klondike", args, workroot,
                      min(deadline, time.monotonic() + KLONDIKE_BUDGET_MIN * 60), KLONDIKE_BOOT_TIMEOUT)
    aggregate(routable, boots, langs, skipped, "routing")
    return {"results": {r["id"]: {"member": r["member"], "version": r["version_tested"],
                                  "skill_id": r["plugin_ids"][0], "routing": r.get("routing")}
                        for _, r in entries},
            "refused": refused, "member_skill_ids": sorted(profile_ids), "not_in_store": not_store,
            "langs": langs, "langs_skipped": skipped, "freeze": freeze,
            "boots": [{k: b.get(k) for k in BOOT_FIELDS} for b in boots]}


COUNTS = ("hit", "wrong_intent", "baseline", "unhandled", "neighbour", "hang", "manual", "not_loaded", "total",
          "asked")


def aggregate(routable, boots, langs, skipped, field="routing"):
    for item, rec in routable:
        routing = rec.setdefault(field, {})
        for run in ("golden", "generated"):
            if routing.get(run, {}).get("status") in ("none", "unavailable", "error"):
                continue
            agg = {k: 0 for k in COUNTS}
            agg.update(misses=[], collisions=[], langs=[], langs_failed=[])
            for b in boots:
                r = (b.get("results") or {}).get(item["id"], {}).get(run)
                if b.get("status") == "boot_failed":
                    agg["langs_failed"].append(b["lang"])
                    continue
                if not r:
                    continue
                agg["langs"].append(b["lang"])
                if b.get("status") == "partial":
                    agg.setdefault("langs_partial", []).append(b["lang"])
                for k in COUNTS:
                    agg[k] += r.get(k, 0)
                for m in r.get("misses", []):
                    agg["misses"].append({**m, "lang": b["lang"]})
                for m in r.get("collisions", []):
                    agg["collisions"].append({**m, "lang": b["lang"]})
            agg["misses"] = agg["misses"][:25]
            agg["collisions"] = agg["collisions"][:10]
            counted = agg["total"] - agg["manual"] - agg["neighbour"] - agg["not_loaded"]
            agg["counted"] = counted
            agg["status"] = "ok" if counted > 0 else "none"
            if counted <= 0:
                agg["reason"] = ("could not boot with the baseline" if agg["langs_failed"]
                                 else "the routing budget ran out before its rows" if agg.get("langs_partial")
                                 else "no rows in the languages routed")
            if run == "golden":
                agg["langs_not_routed"] = skipped
            routing[run] = agg
        g = routing.get("golden", {})
        if field == "routing" and g.get("status") == "ok" and g["hit"] / g["counted"] >= LEVEL3_RATIO:
            rec["level"] = 3


def write_pass(args, name, out):
    freeze = out.pop("freeze", "")
    if freeze:
        Path(args.out).with_name(f"{name}-freeze.txt").write_text(freeze)
    Path(args.out).with_name(f"{name}.json").write_text(json.dumps(out, indent=2))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--channel", required=True)
    ap.add_argument("--constraints", required=True)
    ap.add_argument("--base-venv", required=True)
    ap.add_argument("--items", required=True, help="JSON list from plan.py")
    ap.add_argument("--out", required=True)
    ap.add_argument("--install-timeout", type=int, default=900)
    # Generous: a skill with ~20 languages trains ~20 padatious containers
    # before READY (~200s locally, slower on a 2-core hosted runner). A
    # boot that exceeds this is reported as a failure, so it must not be
    # tight enough to catch merely slow-but-correct skills.
    ap.add_argument("--boot-timeout", type=int, default=900)
    # Level 3 (routing). Without --baseline the shard stops at level 2.
    ap.add_argument("--baseline", default="", help="JSON from plan.py: installer requirements + pipeline")
    ap.add_argument("--klondike", default="", help="JSON from plan.py for the channel's Klondike job: "
                    "the profile and the skills to route against it (no items of its own)")
    ap.add_argument("--generator", default="", help="an `ovoscope` executable with `generate` (may be absent)")
    ap.add_argument("--route-timeout", type=float, default=15.0, help="seconds per utterance")
    ap.add_argument("--deadline-minutes", type=float, default=300,
                    help="no new routing boot starts after this many minutes (job time limit)")
    args = ap.parse_args()
    started_at = time.monotonic()
    baseline = json.loads(args.baseline) if args.baseline else None
    args.baseline = (baseline or {}).get("requirements") or []
    args.pipeline = (baseline or {}).get("pipeline") or []
    args.exclude_ids = (baseline or {}).get("exclude_ids") or []
    args.klondike = json.loads(args.klondike) if args.klondike else None

    items = json.loads(Path(args.items).read_text())
    results = []
    with tempfile.TemporaryDirectory(prefix="compat-") as workroot:
        # Canary: an empty MiniCroft on the untouched base venv. If the test
        # driver itself cannot boot on this channel, no package is to blame,
        # so every item becomes "error" (retried, never published as a ✗).
        canary_out = Path(workroot) / "canary.json"
        rc, out = run([str(Path(args.base_venv) / "bin" / "python"), str(PROBE), "--kind", "canary",
                       "--out", str(canary_out), "--max-wait", str(args.boot_timeout)],
                      args.boot_timeout + TRAINED_MAX + 120, Path(workroot) / "canary.log")
        canary = json.loads(canary_out.read_text()) if canary_out.exists() else \
            {"status": "fail", "reason": "canary timed out" if rc is None else f"canary crashed (exit {rc})"}
        Path(args.out).with_name("canary.json").write_text(
            json.dumps({**canary, "log_excerpt": excerpt(out) if canary.get("status") != "pass" else ""}, indent=2))
        print(f"==> canary: {canary.get('status')} {canary.get('reason', '')} "
              f"driver={canary.get('driver')}", flush=True)
        if canary.get("status") != "pass":
            now = datetime.now(timezone.utc).isoformat(timespec="seconds")
            for item in items:
                results.append({"id": item["id"], "channel": args.channel, "key": item["key"],
                                "kind": item["kind"], "package": item["package"],
                                "requested_version": item.get("version"), "tested_at": now,
                                "level": 0, "status": "error", "stage": "setup",
                                "reason": "test driver cannot boot on this channel: "
                                          + str(canary.get("reason", ""))[:300]})
            Path(args.out).write_text(json.dumps(results, indent=2))
            return 0

        for n, item in enumerate(items, 1):
            print(f"==> [{n}/{len(items)}] {args.channel} {item['kind']} {item['package']} "
                  f"{item.get('version') or '(channel pin)'}", flush=True)
            rec = test_item(item, args, workroot)
            print(f"    {rec['status']} level={rec['level']} {rec.get('reason', '')} "
                  f"({rec['duration_seconds']}s)", flush=True)
            results.append(rec)
            # Written after every item, so a job killed by its time limit
            # still uploads what it finished.
            Path(args.out).write_text(json.dumps(results, indent=2))

        deadline = started_at + args.deadline_minutes * 60
        if args.klondike:
            print("==> Klondike job: the profile, and every skill against it", flush=True)
            try:
                out = klondike_job(args, workroot, deadline)
            except Exception as e:  # noqa: BLE001
                out = {"error": f"{type(e).__name__}: {e}"[:500]}
            write_pass(args, "klondike", out)
        elif args.baseline:
            passes = [("routing", "route", {"requirements": args.baseline, "pipeline": args.pipeline,
                                            "exclude_ids": args.exclude_ids},
                       "the default skills", ROUTE_BUDGET_MIN)]
            try:
                routable, all_runs = prepare_shard(items, results, args, workroot)
            except Exception as e:  # noqa: BLE001 - level 3 trouble never loses levels 1-2
                routable, all_runs = [], {}
                print(f"    level 3 aborted: {e}", flush=True)
            for field, name, spec, label, budget_min in passes if routable else []:
                print(f"==> level 3: routing against {label} ({', '.join(spec['requirements'])})", flush=True)
                try:
                    out = route_pass(routable, all_runs, spec, field, args, workroot, deadline, label, budget_min)
                except Exception as e:  # noqa: BLE001
                    out = {"error": f"{type(e).__name__}: {e}"[:500]}
                    print(f"    {name} aborted: {out['error']}", flush=True)
                if out:
                    write_pass(args, name, out)
                # Written after every pass: a job killed later keeps this one.
                Path(args.out).write_text(json.dumps(results, indent=2))
    Path(args.out).write_text(json.dumps(results, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
