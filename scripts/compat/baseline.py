"""The baseline a level 3 routing test runs against: what the OVOS installer
puts on a default device (issue #6, "what a normal install is").

Read live from OpenVoiceOS/ovos-installer, like the channel constraints:
  * skills: the installer's skills-requirements.txt template, rendered for
    its default choices (profile "ovos", "skills" feature on, "extra skills"
    off, ggwave off). Today that is
    ovos-core[skills-essential,skills-internet,skills-audio], so which skill
    versions land is decided by the channel's constraints, per channel.
  * pipeline: the intent pipeline order from the installer's mycroft.conf
    template.

Both go into the level 3 key, so an installer change re-tests level 3.
Used by plan.py (stdlib + jinja2 only).

The Klondike profile (issue #13) is the second baseline, built on this one;
see read_profile() below.
"""
import hashlib
import json
import re
import urllib.request

INSTALLER_RAW = "https://raw.githubusercontent.com/OpenVoiceOS/ovos-installer/main/ansible/roles"
SKILLS_TEMPLATE = f"{INSTALLER_RAW}/ovos_virtualenv/templates/virtualenv/skills-requirements.txt.j2"
CONFIG_TEMPLATE = f"{INSTALLER_RAW}/ovos_config/templates/mycroft.conf.j2"
# The installer's own defaults (ansible/roles/ovos_installer/defaults/main.yml).
DEFAULT_VARS = {"ovos_installer_profile": "ovos", "ovos_installer_enable_ggwave": False,
                "ovos_installer_feature_skills": True, "ovos_installer_feature_extra_skills": False}
PIPELINE_RE = re.compile(r'"pipeline"\s*:\s*\[(.*?)\]', re.S)


def _fetch(url, timeout=30):
    req = urllib.request.Request(url, headers={"User-Agent": "ovos-klondike-mercantile compat"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode()


def render_requirements(template_text, overrides=None):
    """Requirement lines of the skills template under the default choices.
    Variables the template grows later render as false (ChainableUndefined),
    i.e. an optional extra stays off unless it is one of the defaults above."""
    import jinja2
    env = jinja2.Environment(undefined=jinja2.ChainableUndefined)
    text = env.from_string(template_text).render(**{**DEFAULT_VARS, **(overrides or {})})
    lines = []
    for line in text.splitlines():
        line = line.split("#", 1)[0].strip()
        if line:
            lines.append(line)
    return lines


def parse_pipeline(template_text):
    m = PIPELINE_RE.search(template_text)
    return re.findall(r'"([^"]+)"', m.group(1)) if m else []


def load():
    """{"requirements": [...], "pipeline": [...], "sha256": ..., "source": ...}"""
    requirements = render_requirements(_fetch(SKILLS_TEMPLATE))
    pipeline = parse_pipeline(_fetch(CONFIG_TEMPLATE))
    if not requirements:
        raise RuntimeError("installer skills template rendered no requirements")
    spec = {"requirements": requirements, "pipeline": pipeline,
            "profile": DEFAULT_VARS["ovos_installer_profile"]}
    spec["sha256"] = hashlib.sha256(json.dumps(spec, sort_keys=True).encode()).hexdigest()
    spec["source"] = "OpenVoiceOS/ovos-installer@main (default profile, skills on, extra skills off)"
    return spec


# --- The Klondike profile (issue #13) --------------------------------------
# A second, larger baseline: the installer's defaults as above, plus the
# installer's "extra skills" (its extra-skills template, rendered with that
# feature on), plus the curated entries in compat/klondike-profile.toml.
# Which curated entries are in the profile on a channel is decided by
# plan.py (level 2 on that channel); this module only reads and resolves.

EXTRA_TEMPLATE = f"{INSTALLER_RAW}/ovos_virtualenv/templates/virtualenv/extra-skills-requirements.txt.j2"
PROFILE_FILE = "compat/klondike-profile.toml"
# ovos-core 1.x pipeline names (and the short forms in plugin READMEs) for
# the installer's plugin stage ids, so a profile entry may name either.
STAGE_ALIASES = {
    "stop_high": "ovos-stop-pipeline-plugin-high",
    "stop_medium": "ovos-stop-pipeline-plugin-medium",
    "stop_low": "ovos-stop-pipeline-plugin-low",
    "converse": "ovos-converse-pipeline-plugin",
    "ocp_high": "ovos-ocp-pipeline-plugin-high",
    "ocp_medium": "ovos-ocp-pipeline-plugin-medium",
    "ocp_low": "ovos-ocp-pipeline-plugin-low",
    "padatious_high": "ovos-padatious-pipeline-plugin-high",
    "padatious_medium": "ovos-padatious-pipeline-plugin-medium",
    "padatious_low": "ovos-padatious-pipeline-plugin-low",
    "adapt_high": "ovos-adapt-pipeline-plugin-high",
    "adapt_medium": "ovos-adapt-pipeline-plugin-medium",
    "adapt_low": "ovos-adapt-pipeline-plugin-low",
    "fallback_high": "ovos-fallback-pipeline-plugin-high",
    "fallback_medium": "ovos-fallback-pipeline-plugin-medium",
    "fallback_low": "ovos-fallback-pipeline-plugin-low",
    "common_qa": "ovos-common-query-pipeline-plugin",
    "common_query": "ovos-common-query-pipeline-plugin",
}


def read_profile(repo_root="."):
    """The curated part: {"skills": [...], "pipeline": [...]} from the TOML."""
    import tomllib
    from pathlib import Path
    data = tomllib.loads((Path(repo_root) / PROFILE_FILE).read_text())
    skills, plugins = [], []
    for s in data.get("skill") or []:
        if not isinstance(s.get("id"), str):
            raise ValueError(f"{PROFILE_FILE}: a [[skill]] without an id")
        skills.append({k: str(s[k]) for k in ("id", "function", "note") if k in s})
    for p in data.get("pipeline") or []:
        if not (isinstance(p.get("id"), str) and isinstance(p.get("stage"), str)):
            raise ValueError(f"{PROFILE_FILE}: a [[pipeline]] needs id and stage")
        if ("after" in p) == ("before" in p):
            raise ValueError(f"{PROFILE_FILE}: {p['id']} needs exactly one of after/before")
        plugins.append({k: str(p[k]) for k in ("id", "stage", "after", "before", "note") if k in p})
    ids = [s["id"] for s in skills] + [p["id"] for p in plugins]
    if len(ids) != len(set(ids)):
        raise ValueError(f"{PROFILE_FILE}: an id is listed twice")
    return {"skills": skills, "pipeline": plugins}


def insert_stages(pipeline, plugins):
    """(installer pipeline with the plugins' stages inserted, stages added,
    {stage: why not}). A stage the installer already has is not added; an
    anchor the installer pipeline lacks leaves the stage out, said why."""
    out = list(pipeline)
    added, skipped = [], {}
    for p in plugins:
        stage = p["stage"]
        if stage in out:
            skipped[stage] = "already in the installer's pipeline"
            continue
        anchor = p.get("after") or p.get("before")
        anchor = STAGE_ALIASES.get(anchor, anchor)
        if anchor not in out:
            skipped[stage] = f"{anchor} is not in the installer's pipeline"
            continue
        i = out.index(anchor) + (1 if p.get("after") else 0)
        out.insert(i, stage)
        added.append(stage)
    return out, added, skipped


# A provider skill only works behind the pipeline plugin it provides for, the
# way a skill only works with its own dependencies. When a shard routes such
# a skill (level 2 saw it register with that pipeline), the normal-install
# pass installs the plugin and inserts its stages, where its README puts them.
COMPANION_PIPELINES = {
    "common_reading": {
        "requirement": "ovos-common-reading-pipeline-plugin",
        "stages": [
            {"stage": "ovos-common-reading-pipeline-plugin-high", "after": "stop_high"},
            {"stage": "ovos-common-reading-pipeline-plugin-low", "before": "ovos-fallback-pipeline-plugin-low"},
        ],
    },
}


def with_companions(spec, registrations):
    """(spec with the companion pipelines the given level-2 registrations
    need, {kind: stages added}). `registrations` is a list of the routed
    skills' registration dicts; spec is {requirements, pipeline, ...}."""
    kinds = sorted({k for regs in registrations for k in (regs or {}) if k in COMPANION_PIPELINES})
    if not kinds:
        return spec, {}
    out = dict(spec)
    reqs, pipeline, added = list(spec.get("requirements") or []), list(spec.get("pipeline") or []), {}
    for kind in kinds:
        comp = COMPANION_PIPELINES[kind]
        if comp["requirement"] not in reqs:
            reqs.append(comp["requirement"])
        pipeline, stages, _ = insert_stages(pipeline, comp["stages"])
        added[kind] = stages
    out["requirements"], out["pipeline"] = reqs, pipeline
    return out, added


def load_extra_requirements():
    """The installer's extra-skills template, rendered with that feature on."""
    lines = render_requirements(_fetch(EXTRA_TEMPLATE), {"ovos_installer_feature_extra_skills": True})
    if not lines:
        raise RuntimeError("installer extra-skills template rendered no requirements")
    return lines


if __name__ == "__main__":
    print(json.dumps(load(), indent=2))
