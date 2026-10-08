#!/usr/bin/env python3
"""The profile report: what passes in each install profile, per channel.

Three profiles that build on each other:
  default   the OVOS installer's default skills and pipeline
  extra     + the installer's "extra skills"
  klondike  + the curated entries of compat/klondike-profile.toml (#13)

Nothing is tested here: the rows are the results already in
docs/compat/results.json, grouped by profile. Written to
docs/compat/profile-report.json in the ovos-profile-report/1 format
(docs/schemas/ovos-profile-report-1.json), which names no store as its key:
rows are keyed by the runtime skill/plugin id, so ovos-tui-client can write
the same report for a device (ovos-tui-client#62); store_id is optional.

Run after publish.py: python3 scripts/compat/profile_report.py [--repo .]
"""
import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from compat.feed import (CHANNEL_ORDER, LAST_RESORT_NOTE, LEVEL3_LANG, LEVEL3_RATIO, label, last_resort,  # noqa: E402
                         routing_counts)

SCHEMA = "ovos-profile-report/1"
STAGE_SUFFIX = re.compile(r"-(high|medium|low)$")


def runtime_index(results):
    """runtime id (skill_id or pipeline plugin id) -> store id."""
    out = {}
    for store_id, per_channel in sorted(results.items()):
        for rec in per_channel.values():
            for pid in rec.get("plugin_ids") or []:
                out.setdefault(pid, store_id)
    return out


def store_index(skills):
    """Fallback for entries without a test result: runtime id -> store id,
    from docs/skills.json (skill_id, then package name guesses)."""
    by_sid = {e["skill_id"]: e["id"] for e in skills if e.get("skill_id")}
    by_pkg = {e["package_name"]: e["id"] for e in skills if e.get("package_name")}
    by_repo = {e["id"].lower(): e["id"] for e in skills}  # "<owner>-<repo>"

    def find(rid):
        if rid in by_repo.values():
            return rid
        if rid in by_sid:
            return by_sid[rid]
        name, _, owner = rid.partition(".")
        for guess in (name, re.sub(r"^skill-ovos-", "ovos-skill-", name),
                      re.sub(r"-pipeline(-plugin)?$", "", name)):
            if guess in by_pkg:
                return by_pkg[guess]
            if owner and f"{owner}-{guess}".lower() in by_repo:
                return by_repo[f"{owner}-{guess}".lower()]
        return None
    return find


def stage_plugin(stage):
    """ovos-padatious-pipeline-plugin-high -> ovos-padatious-pipeline-plugin."""
    return STAGE_SUFFIX.sub("", stage)


def row(runtime_id, kind, store_id, rec, kres, note=None, archived=False, ptake=None):
    """One entry of a profile on one channel."""
    out = {"runtime_id": runtime_id, "store_id": store_id, "kind": kind}
    if archived:
        out["archived"] = True
    if not store_id:
        out.update(state="not_in_store", label="not in the store", level=None)
    else:
        text, state = label(rec)
        out.update(state=state, label=text, level=(rec or {}).get("level") if rec else None)
        if rec:
            out["kind"] = rec.get("kind") or kind
            if rec.get("version_tested"):
                out["version"] = rec["version_tested"]
            if rec.get("tested_at"):
                out["tested_at"] = rec["tested_at"]
    resort = last_resort(rec)
    if resort:
        # graded by level 2 (#75): no golden counts, here or from the Klondike job
        note = "; ".join(filter(None, [note, LAST_RESORT_NOTE]))
    golden = routing_counts(rec, "golden") if rec and not resort else None
    out["golden"] = {"hit": golden[0], "counted": golden[1]} if golden else None
    if golden:
        # The languages behind the count, so the compare view only compares
        # channels on the languages they all routed: en-US where the result
        # has per-language counts (#67), else every language routed.
        g = rec["routing"]["golden"]
        if g.get("by_lang"):
            out["golden"]["langs"] = [LEVEL3_LANG]
            out["golden"]["by_lang"] = dict(g["by_lang"])
        elif g.get("langs"):
            out["golden"]["langs"] = list(g["langs"])
    k = routing_counts(kres, "golden") if kres and not resort else None
    out["klondike"] = {"hit": k[0], "counted": k[1]} if k else None
    out["gold"] = bool(golden and k and (out["level"] or 0) >= 3 and k[0] / k[1] >= LEVEL3_RATIO)
    if kind == "pipeline" and ptake is not None:
        # Level 3 for a pipeline plugin (#52), from the Klondike job: the
        # rows it took for the skill they belong to, and the rows it took
        # from their skill. Only where the core attributes matches.
        out["pipeline_route"] = ptake
        out["gold"] = bool(ptake.get("measured") and ptake.get("reaches", 0) > 0 and ptake.get("takes", 0) == 0
                           and out["state"] in ("pass", "warn"))
    if note:
        out["note"] = note
    return out


def summary(rows):
    loads = [r for r in rows if r["state"] in ("pass", "warn")]
    return {
        "total": len(rows),
        "in_store": sum(1 for r in rows if r["state"] != "not_in_store"),
        "loads": len(loads),
        "fails": sum(1 for r in rows if r["state"] == "fail"),
        "not_testable": sum(1 for r in rows if r["state"] == "unsupported"),
        "untested": sum(1 for r in rows if r["state"] == "untested"),
        "not_in_store": sum(1 for r in rows if r["state"] == "not_in_store"),
        "routes": sum(1 for r in loads if (r["level"] or 0) >= 3),
        "gold": sum(1 for r in rows if r["gold"]),
    }


def sort_key(r):
    # pipeline first (it carries everything else), then by id
    return (r["kind"] != "pipeline", (r["store_id"] or r["runtime_id"]).lower())


def channel_report(doc, channel, rt, find=lambda rid: None, archived=frozenset()):
    results = doc.get("results") or {}
    route = ((doc.get("channels") or {}).get(channel) or {}).get("route") or {}
    kl = (doc.get("klondike") or {}).get(channel) or {}
    prof = kl.get("profile") or {}
    job = (kl.get("job") or {}).get("results") or {}
    if not route.get("baseline_ids"):
        return None

    added = set(prof.get("added_stages") or [])
    inst = (doc.get("installer") or {}).get(channel) or {}
    kjob = kl.get("job") or {}
    measured = kjob.get("attribution") is True
    ptakes = kjob.get("pipelines") or {}

    def ptake_of(rid, rec):
        """What the Klondike job saw this pipeline plugin take, by any of its ids
        (None for a job from before #52, which did not count it)."""
        if "pipelines" not in kjob:
            return None
        ids = list(dict.fromkeys([rid] + list((rec or {}).get("plugin_ids") or [])))
        found = [ptakes[i] for i in ids if i in ptakes]
        out = {"measured": measured, "reaches": sum(f.get("reaches", 0) for f in found),
               "takes": sum(f.get("takes", 0) for f in found)}
        ex = [e for f in found for e in f.get("examples") or []][:5]
        if ex:
            out["examples"] = ex
        return out
    seen = set()

    def collect(ids, kind, notes=None):
        rows = []
        for rid in ids:
            sid = rt.get(rid) or (rid if rid in results else None) or find(rid)
            key = sid or rid
            if key in seen:
                continue
            seen.add(key)
            rec = (results.get(sid) or {}).get(channel) if sid else None
            if sid and rec and rec.get("plugin_ids") and rid == sid:
                rid = rec["plugin_ids"][0]
            elif rid == sid and (inst.get(sid) or {}).get("package"):
                rid = inst[sid]["package"]  # not tested yet: the pip name it is installed as
            rows.append(row(rid, kind, sid, rec, job.get(sid) if sid else None, (notes or {}).get(key),
                            archived=sid in archived, ptake=ptake_of(rid, rec) if kind == "pipeline" else None))
        return sorted(rows, key=sort_key)

    # What the installer installs on this channel (#54), as plan.py read it
    # from ovos-core's extras: it decides Default vs Extra. The ids the
    # routing job saw installed are added after it, so nothing it booted
    # goes missing (and one the store lacks still shows as not in the store).
    inst_ids = lambda profile, kind: sorted(i for i, m in inst.items()  # noqa: E731
                                            if m.get("profile") == profile and m.get("kind") == kind)
    pipe_default = [stage_plugin(s) for s in route.get("pipeline_used") or route.get("pipeline_requested") or []
                    if s not in added]
    default = collect(inst_ids("default", "pipeline") + pipe_default, "pipeline") \
        + collect(inst_ids("default", "skill") + route["baseline_ids"], "skill")
    default.sort(key=sort_key)

    curated = prof.get("curated") or []
    curated_ids = {c["id"] for c in curated}
    curated_runtime = {pid for sid in curated_ids
                       for rec in (results.get(sid) or {}).values() for pid in rec.get("plugin_ids") or []}
    extra_ids = [s for s in prof.get("skill_ids") or [] if s not in curated_runtime
                 and rt.get(s) not in curated_ids]
    extra = collect(inst_ids("extra", "skill") + extra_ids, "skill")

    notes = {c["id"]: c.get("function") for c in curated}
    for sid, why in (prof.get("left_out") or {}).items():
        notes[sid] = f"left out on {channel}: {why}"
    klondike = collect([stage_plugin(s) for s in sorted(added)], "pipeline", notes) \
        + collect([c["id"] for c in curated], "skill", notes)
    klondike.sort(key=sort_key)
    left_out = set(prof.get("left_out") or {})
    for r in klondike:
        r["in_profile"] = r["store_id"] not in left_out

    profiles = [
        {"id": "default", "name": "Default", "builds_on": None,
         "source": route.get("baseline_source"), "entries": default},
        {"id": "extra", "name": "Extra", "builds_on": "default",
         "source": "OVOS installer extra skills: " + ", ".join(prof.get("extra_requirements") or []),
         "entries": extra},
        {"id": "klondike", "name": "Klondike", "builds_on": "extra",
         "source": "compat/klondike-profile.toml (curated)", "entries": klondike},
    ]
    running = []
    for p in profiles:
        p["summary"] = summary(p["entries"])
        running += [r for r in p["entries"] if r.get("in_profile", True)]
        p["cumulative"] = summary(running)
    # Stages of the installer's pipeline the routing runs had to leave out
    # (not installed, did not load, model did not load): level 3 on this
    # channel ran on an incomplete pipeline (#52). Notes such as "(channel
    # default used: 13 stages)" are not stages.
    boots = [route] + list((kl.get("job") or {}).get("boots") or [])
    not_loaded = sorted({s for b in boots for s in b.get("pipeline_dropped") or [] if not s.startswith("(")})
    return {"run_at": route.get("run_at"), "klondike_run_at": (kl.get("job") or {}).get("run_at"),
            "pipeline_not_loaded": not_loaded,
            "constraints_url": (doc["channels"][channel]).get("constraints_url"), "profiles": profiles}


def build(doc, skills=()):
    rt = runtime_index(doc.get("results") or {})
    find = store_index(skills)
    archived = frozenset(e["id"] for e in skills if e.get("archived"))
    channels = {}
    for ch in CHANNEL_ORDER:
        rep = channel_report(doc, ch, rt, find, archived)
        if rep:
            channels[ch] = rep
    # Stamped with the results' time, not now: the file only changes when
    # the results do, so publishing it never makes an empty commit.
    return {"schema": SCHEMA, "generated_at": doc.get("generated_at"), "channels": channels}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", default=".")
    args = ap.parse_args()
    docs = Path(args.repo) / "docs"
    doc = json.loads((docs / "compat" / "results.json").read_text())
    skills = json.loads((docs / "skills.json").read_text())
    out = build(doc, skills["skills"] if isinstance(skills, dict) else skills)
    (docs / "compat" / "profile-report.json").write_text(json.dumps(out, indent=1, ensure_ascii=False) + "\n")
    for ch, rep in out["channels"].items():
        print(ch, " | ".join(f"{p['name']}: {p['summary']['loads']}/{p['summary']['total']}" for p in rep["profiles"]))


if __name__ == "__main__":
    main()
