#!/usr/bin/env python3
"""Merge test-shard artifacts into docs/, in the job that holds write access.

The artifacts were produced by a job that ran arbitrary PyPI code, so they
are treated as untrusted data:
  * a record is only accepted for an (id, channel) that plan.py put in THAT
    shard, with the key plan.py computed for it;
  * only known fields are kept, with type checks and length caps;
  * log excerpts are stored as plain text (the site renders them with
    textContent, never as HTML).

An "error" result (infra trouble) never replaces an earlier pass/fail; it is
kept beside it as last_error, and plan.py retries it on the next run.

Writes: docs/compat/results.json, docs/compat/stack-<channel>.txt and
docs/badges/<badge_id>/<channel>.json. Never the feed (see below).
"""
import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from compat.feed import CHANNEL_ORDER, FINAL_STATUSES, SAFE_ID, badge_ids, is_candidate, load_results, shields  # noqa: E402

STR_FIELDS = {"id": 200, "channel": 20, "key": 32, "kind": 20, "package": 200,
              "requested_version": 64, "version_tested": 64, "tested_at": 40,
              "status": 12, "stage": 20, "reason": 600, "log_excerpt": 4000, "driver": 80, "languages_source": 10}
NUM_FIELDS = {"level", "duration_seconds", "boot_seconds"}
LIST_FIELDS = {"plugin_ids": 20, "languages_booted": 60, "languages_missing": 60,
               "warnings": 10, "stages": 20}


def clean(rec):
    out = {}
    for k, cap in STR_FIELDS.items():
        if isinstance(rec.get(k), str):
            out[k] = rec[k][:cap]
    for k in NUM_FIELDS:
        if isinstance(rec.get(k), (int, float)) and not isinstance(rec.get(k), bool):
            out[k] = rec[k]
    if isinstance(rec.get("channel_pinned"), bool):
        out["channel_pinned"] = rec["channel_pinned"]
    for k, cap in LIST_FIELDS.items():
        v = rec.get(k)
        if isinstance(v, list):
            out[k] = [str(x)[:200] for x in v[:cap]]
    regs = rec.get("registrations")
    if isinstance(regs, dict):
        out["registrations"] = {
            str(k)[:40]: (v if isinstance(v, int) else [str(x)[:120] for x in v[:20]])
            for k, v in list(regs.items())[:10] if isinstance(v, (int, list))}
    by_lang = rec.get("intents_by_lang")
    if isinstance(by_lang, dict):
        out["intents_by_lang"] = {str(k)[:20]: v for k, v in list(by_lang.items())[:60]
                                  if isinstance(v, int)}
    if out.get("status") not in FINAL_STATUSES + ("error",):
        return None
    out["level"] = out.get("level", 0) if out.get("level") in (0, 1, 2) else 0
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--plan", required=True, help="matrix JSON from plan.py")
    ap.add_argument("--artifacts", required=True, help="dir with shard-<channel>-<n>/ subdirs")
    ap.add_argument("--repo", default=".")
    args = ap.parse_args()

    repo = Path(args.repo)
    docs = repo / "docs"
    plan = json.loads(Path(args.plan).read_text())
    results_path = docs / "compat" / "results.json"
    doc = load_results(results_path)
    results = doc.setdefault("results", {})
    channels_meta = doc.setdefault("channels", {})
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")

    accepted = rejected = 0
    for shard in plan.get("include", []):
        channel, n = shard["channel"], shard["shard"]
        sdir = Path(args.artifacts) / f"shard-{channel}-{n}"
        expected = {i["id"]: i["key"] for i in shard["items"]}
        try:
            records = json.loads((sdir / "results.json").read_text())
        except (OSError, ValueError):
            print(f"warning: no results for {channel} shard {n}", file=sys.stderr)
            continue
        for raw in records if isinstance(records, list) else []:
            rec = clean(raw) if isinstance(raw, dict) else None
            if not rec or rec.get("channel") != channel or expected.get(rec.get("id")) != rec.get("key"):
                rejected += 1
                continue
            per = results.setdefault(rec["id"], {})
            prev = per.get(channel)
            if rec["status"] == "error" and prev and prev.get("status") in FINAL_STATUSES:
                prev["last_error"] = {"tested_at": rec.get("tested_at"), "reason": rec.get("reason")}
            else:
                per[channel] = rec
            accepted += 1
        # Channel metadata from the first shard that has it.
        meta = channels_meta.setdefault(channel, {})
        if meta.get("run_at") != now:
            try:
                stack = json.loads((sdir / "stack.json").read_text())
                meta["stack"] = {"python": str(stack.get("python", ""))[:20],
                                 "packages": {str(k)[:60]: (str(v)[:40] if v else None)
                                              for k, v in list(stack.get("packages", {}).items())[:20]}}
                freeze = (sdir / "stack-freeze.txt").read_text()[:200_000]
                (docs / "compat").mkdir(parents=True, exist_ok=True)
                (docs / "compat" / f"stack-{channel}.txt").write_text(freeze)
                meta.update(run_at=now,
                            constraints_sha256=plan["summary"][channel]["constraints_sha256"],
                            constraints_url=f"https://raw.githubusercontent.com/OpenVoiceOS/OpenVoiceOS/main/constraints-{channel}.txt",
                            harness_sha=plan.get("harness_sha"),
                            runner_version=plan.get("runner_version"))
            except (OSError, ValueError, KeyError):
                pass
    doc["generated_at"] = now
    print(f"accepted {accepted} records, rejected {rejected}")

    # The feed is read, never written: the crawler owns docs/skills.json and
    # skills/*.json and re-attaches the compat field from results.json on
    # every run. Writing it here too would make the crawler's push-rebase
    # conflict on skills.json and lose a whole crawl.
    feed_path = docs / "skills.json"
    entries = json.loads(feed_path.read_text())
    valid = {e["id"] for e in entries}
    doc["results"] = {k: v for k, v in results.items() if k in valid}
    results_path.parent.mkdir(parents=True, exist_ok=True)
    results_path.write_text(json.dumps(doc, indent=2, sort_keys=True) + "\n")

    # Badges: one endpoint per candidate and channel (untested ones too, so
    # a README badge works from the day the skill becomes Looks Complete).
    # Same badge ids as the crawler's compat field (feed.badge_ids).
    candidates = [e for e in entries if is_candidate(e)]
    ids = badge_ids([(e, doc["results"].get(e["id"])) for e in candidates])
    channels = [c for c in CHANNEL_ORDER if c in plan.get("summary", {}) or c in channels_meta]
    badges = docs / "badges"
    for e in candidates:
        bid = ids[e["id"]]
        if not SAFE_ID.match(bid):
            continue
        for channel in channels:
            rec = doc["results"].get(e["id"], {}).get(channel)
            out = badges / bid / f"{channel}.json"
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(json.dumps(shields(channel, rec)) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
