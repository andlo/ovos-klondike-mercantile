"""The stop check (issue #16): route.stop_check against a fake core, and the
result as published and labelled. Run: python3 tests/test_stop.py"""
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "scripts" / "compat"))

import route  # noqa: E402
from compat.feed import label  # noqa: E402
from compat.publish import clean_routing  # noqa: E402

from ovos_bus_client.message import Message  # noqa: E402

fails = 0


def ok(cond, name):
    global fails
    print(("ok   " if cond else "FAIL ") + name)
    fails += 0 if cond else 1


class FakeCore:
    """Enough of MiniCroft for stop_check: emit runs the handler in the
    calling thread, like FakeBus; skills speak with skill_id in context."""

    def __init__(self):
        self.handlers = []
        self.stopped = threading.Event()
        self.bus = self

    def on(self, _event, handler):
        self.handlers.append(handler)

    def remove(self, _event, handler):
        self.handlers.remove(handler)

    def _send(self, msg):
        for h in list(self.handlers):
            h(msg)

    def say(self, original, text, skill_id="count.test"):
        self._send(Message("speak", {"utterance": text}, {**(original.context or {}), "skill_id": skill_id}))

    def emit(self, msg):
        self._send(msg)
        if msg.msg_type != "recognizer_loop:utterance":
            return
        said = msg.data["utterances"][0]
        if said == "stop":
            self._send(Message("mycroft.stop", {}, msg.context))
            self.stopped.set()
        elif said == "count to ten forever":
            n = 0
            while not self.stopped.is_set() and n < 400:
                n += 1
                self.say(msg, str(n))
                time.sleep(0.2)
        elif said == "count and ignore stop":
            for n in range(60):
                self.say(msg, str(n))
                time.sleep(0.2)
        elif said == "count and hang":
            self.say(msg, "one")
            time.sleep(0.5)
            self.say(msg, "two")
            while not self.stopped.is_set():
                time.sleep(0.1)
            time.sleep(30)
        elif said == "what's the weather":
            self.say(msg, "sunny", "weather.test")


def check(utterance, own=("count.test",)):
    return route.stop_check(FakeCore(), utterance, "en-US", ["stop_high"], list(own))


route.STOP_FIRST, route.STOP_SETTLE, route.STOP_GRACE, route.STOP_QUIET, route.STOP_RETURN = 3, 0.6, 1.0, 1.2, 2.5

r = check("count to ten forever")
ok(r["result"] == "stops" and "mycroft.stop" in r["stop_messages"], "a counting skill that honours stop: stops")
r = check("count and ignore stop")
ok(r["result"] == "keeps_going" and r["spoke_after_stop"] > 0 and r["after"], "one that keeps counting: keeps_going")
r = check("count and hang")
ok(r["result"] == "stuck", "quiet after stop, but the handler never returns: stuck")
r = check("what's the weather", ("weather.test",))
ok(r["result"] == "nothing_to_stop", "a one-off answer: nothing to stop")
r = check("nobody knows this")
ok(r["result"] == "silent", "no speech or playback: silent")

# published and labelled
routing = {"golden": {"status": "ok", "hit": 14, "counted": 14, "total": 14},
           "stop": {"result": "keeps_going", "utterance": "count", "spoke_after_stop": 4, "after": ["5"],
                    "lang": "en-US", "evil": "<script>"}}
clean = clean_routing(routing)
ok(clean["stop"] == {"result": "keeps_going", "utterance": "count", "lang": "en-US", "spoke_after_stop": 4,
                     "after": ["5"]}, "publish keeps only the known stop fields")
ok(clean_routing({"stop": {"result": "made-up"}}) is None, "an unknown result is dropped")
rec = {"status": "pass", "level": 3, "routing": clean}
ok(label(rec) == ("✓ 14/14 golden · doesn't stop", "warn"), "label: doesn't stop")
rec["routing"]["stop"] = {"result": "stops"}
ok(label(rec) == ("✓ 14/14 golden · stops", "pass"), "label: stops")
rec["routing"]["stop"] = {"result": "nothing_to_stop"}
ok(label(rec) == ("✓ 14/14 golden", "pass"), "label: nothing to stop shows nothing")

print("\nALL OK" if not fails else f"\n{fails} FAILED")
sys.exit(1 if fails else 0)
