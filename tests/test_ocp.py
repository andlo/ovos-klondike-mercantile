#!/usr/bin/env python3
"""OCP at level 3, without the network: a skill that answers OCP's search
(metronome, rhythm box, tuning fork) takes "start a metronome" through OCP,
not through an intent, and that counts as reaching the skill."""
import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "scripts" / "compat"))

fails = 0
METRONOME = "ovos-skill-metronome.andlo"
OTHER = "ovos-skill-rhythm-box.andlo"


def ok(cond, what):
    global fails
    print(("ok   " if cond else "FAIL ") + what)
    fails += not cond


def msg(t, ctx=None, data=None):
    return SimpleNamespace(msg_type=t, context=ctx or {}, data=data or {})


def tracks(*ids, key="tracks"):
    return {key: [{"uri": f"/{i}/120", "skill_id": i, "match_confidence": 100} for i in ids]}


def test_claimant():
    try:
        from route import claimant, expected_fired
    except Exception as e:  # noqa: BLE001 - route.py needs the test venv's ovos packages
        print(f"skip OCP tests: {e}")
        return
    known = {METRONOME, OTHER}

    # No player in the core under test: OCP lists the results, best first.
    recs = [msg("recognizer_loop:utterance"), msg("ocp:play"),
            msg("ovos.common_play.query.response", data={"skill_id": OTHER, "results": []}),
            msg("ovos.common_play.query.response", data={"skill_id": METRONOME, "results": [{}]}),
            msg("ovos.common_play.reset"),
            msg("ovos.common_play.search.populate", data=tracks(METRONOME, OTHER, key="playlist"))]
    who, fired = claimant(recs, known)
    ok(who == METRONOME and "ocp:play" in fired, f"populate: the first track's skill ({who}, {fired})")

    # With a player: the play message names the picked track.
    recs = [msg("ocp:play"), msg("ovos.common_play.play", data=tracks(OTHER)),
            msg("ovos.common_play.search.populate", data=tracks(OTHER, METRONOME))]
    who, _ = claimant(recs, known)
    ok(who == OTHER, f"play: the played track's skill ({who})")

    # OCP picked a skill that is not one we know (a default skill): nobody of ours.
    recs = [msg("ovos.common_play.search.populate", data=tracks("ovos-skill-somafm.openvoiceos"))]
    who, _ = claimant(recs, known)
    ok(who is None, "a pick outside the known skills is not credited")

    # A fired intent still wins over OCP.
    recs = [msg(f"{OTHER}:start_beat"), msg("ovos.common_play.search.populate", data=tracks(METRONOME))]
    who, fired = claimant(recs, known)
    ok(who == OTHER and "ocp:play" not in fired, "a fired intent wins")

    ok(expected_fired(METRONOME, "start_metronome", ["ocp:play"]), "an intent row is met through OCP")
    ok(expected_fired(METRONOME, "start_metronome", ["ocp:play"], "ocp"), "an OCP row is met through OCP")
    ok(not expected_fired(METRONOME, "start_metronome", [f"{METRONOME}:start_metronome"], "ocp"),
       "an OCP row is not met by the intent")
    ok(not expected_fired(METRONOME, "set_metronome", [f"{METRONOME}:start_metronome"]),
       "another intent is still wrong")
    ok(expected_fired(METRONOME, "set_metronome", [f"{METRONOME}:set_metronome"], "padatious"),
       "the intent itself")

if __name__ == "__main__":
    test_claimant()
    print("\nALL OK" if not fails else f"\n{fails} FAILED")
    sys.exit(1 if fails else 0)
