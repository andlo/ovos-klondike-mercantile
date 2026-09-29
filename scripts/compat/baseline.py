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


def render_requirements(template_text):
    """Requirement lines of the skills template under the default choices.
    Variables the template grows later render as false (ChainableUndefined),
    i.e. an optional extra stays off unless it is one of the defaults above."""
    import jinja2
    env = jinja2.Environment(undefined=jinja2.ChainableUndefined)
    text = env.from_string(template_text).render(**DEFAULT_VARS)
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


if __name__ == "__main__":
    print(json.dumps(load(), indent=2))
