#!/usr/bin/env python3
"""One-shot Shoko metadata bootstrap for two missing Nekopara standalone works.

READ-ONLY by default. Exactly two targeted AniDB work GETs; no /File scan.
Only --apply --confirm CREATE_2_NEKOPARA_WORKS may enqueue up to two Shoko
metadata requests, durably journaled BEFORE each POST. No XRefs.

Usage:
  python3 nekopara_ova_ona_bootstrap.py --report /root/nekopara-works-dry-run.json
  python3 nekopara_ova_ona_bootstrap.py --apply \
      --confirm CREATE_2_NEKOPARA_WORKS --report /root/nekopara-works-requested.json
  python3 nekopara_ova_ona_bootstrap.py --check \
      --report /root/nekopara-works-episodes.json
"""
from __future__ import annotations

import argparse
from collections import Counter
import json
import os
from pathlib import Path
import time

from shoko_reconcile import ShokoAPI
from targeted_metadata_bootstrap import (
    atomic_json, episode_details, exclusive_state_lock,
)

STATE = Path("/var/lib/shoko-reconcile/nekopara-ova-ona-20261116.state.json")
WORKS = (
    {
        "anidb_id": 12622,
        "title": "Nekopara OVA (2017)",
        "file_id": 2909,
        "path": "NEKOPARA_[OVA]_[AniLibria_Tv]_[WEB-Rip_1080p].mkv",
    },
    {
        "anidb_id": 14206,
        "title": "Nekopara: Koneko no Hi no Yakusoku ONA",
        "file_id": 2850,
        "path": "Nekopara_Koneko_no_Hi_no_Yakusoku_[ONA]_[AniLibria_TV]_[WEBRip_1080p].mkv",
    },
)
ALLOWED_AIDS = frozenset((12622, 14206))


def load_state(path=STATE):
    if not path.exists():
        return {"schema": 1, "attempts": {}}
    value = json.loads(path.read_text(encoding="utf-8"))
    if (not isinstance(value, dict) or value.get("schema") != 1
            or not isinstance(value.get("attempts"), dict)
            or not set(value["attempts"]).issubset({str(i) for i in ALLOWED_AIDS})):
        raise ValueError("Unexpected Nekopara attempt journal; refusing requests")
    return value


def preflight(api, state, *, check=False):
    if len(WORKS) != 2 or {w["anidb_id"] for w in WORKS} != ALLOWED_AIDS:
        raise ValueError("Only the two pinned Nekopara AniDB works are allowed")
    if not isinstance(state, dict) or not isinstance(state.get("attempts"), dict):
        raise ValueError("Invalid attempt journal")
    rows = []
    for work in WORKS:
        aid = work["anidb_id"]
        row = dict(work)
        try:
            series = api.local_series(aid)
            if series is None:
                row["status"] = ("previously_requested_pending" if str(aid) in
                                 state["attempts"] else "missing")
                if str(aid) in state["attempts"]:
                    row["attempt"] = state["attempts"][str(aid)]
            else:
                ids = (series or {}).get("IDs") or {}
                sid = int(ids.get("ID") or 0)
                actual_aid = int(ids.get("AniDB") or 0)
                if sid < 1 or actual_aid != aid:
                    row.update(status="blocked_identity_mismatch",
                               error="Local Shoko series and AniDB IDs differ")
                else:
                    row.update(status="present", shoko_series_id=sid)
                    if check:
                        row["episodes"] = episode_details(api, sid)
                        row["status"] = ("present_ready" if row["episodes"]
                                         else "present_without_episodes")
        except Exception as exc:
            row.update(status="api_error",
                       error=f"{type(exc).__name__}: {str(exc)[:200]}")
        rows.append(row)
    return {
        "mode": "check" if check else "dry_run",
        "works": rows,
        "counts": dict(Counter(row["status"] for row in rows)),
        "scope": {
            "targeted_work_gets": 2,
            "episode_inventory_gets": sum("episodes" in row for row in rows),
            "unrecognized_file_scans": 0,
            "media_walks": 0, "xref_writes": 0, "background_jobs_created": 0,
        },
        "caveat": "Only a verified AniDB episode inventory can authorize a later exact XRef.",
    }


def apply(api, state, persist, *, sleep=time.sleep, now=time.time):
    report = preflight(api, state)
    if any(row["status"] in ("api_error", "blocked_identity_mismatch")
           for row in report["works"]):
        report.update(mode="apply_aborted_preflight", submitted=0)
        return report
    report.update(mode="apply", submitted=0, attempted=0)
    for row in report["works"]:
        if row["status"] != "missing":
            continue
        if report["attempted"]:
            sleep(2)
        aid = row["anidb_id"]
        # Persist prior to dispatch: an uncertain reply must NEVER cause a
        # duplicate metadata refresh on subsequent CLI runs.
        state["attempts"][str(aid)] = {
            "attempted_at_epoch": int(now()), "outcome": "dispatch_uncertain"}
        persist(state)
        report["attempted"] += 1
        try:
            api.refresh_series(aid)
        except Exception as exc:
            state["attempts"][str(aid)]["outcome"] = "request_error_uncertain"
            persist(state)
            row.update(status="request_error_uncertain",
                       error=f"{type(exc).__name__}: {str(exc)[:200]}")
            break
        state["attempts"][str(aid)]["outcome"] = "requested"
        persist(state)
        row["status"] = "requested"
        report["submitted"] += 1
    report["counts"] = dict(Counter(row["status"] for row in report["works"]))
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://127.0.0.1:8111")
    parser.add_argument("--state", type=Path, default=STATE)
    parser.add_argument("--report", type=Path)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--confirm", default="")
    args = parser.parse_args(argv)
    if args.apply and args.check:
        parser.error("--apply and --check are mutually exclusive")
    if args.apply and args.confirm != "CREATE_2_NEKOPARA_WORKS":
        parser.error("Use --confirm CREATE_2_NEKOPARA_WORKS to enqueue metadata")
    key = os.getenv("SHOKO_API_KEY")
    if not key:
        parser.error("SHOKO_API_KEY is missing; never pass the key on command line")
    api = ShokoAPI(args.url, key)
    if args.apply:
        try:
            with exclusive_state_lock(args.state):
                report = apply(
                    api, load_state(args.state),
                    persist=lambda value: atomic_json(args.state, value))
        except BlockingIOError:
            parser.error("Another Nekopara metadata request process holds the lock")
    else:
        report = preflight(api, load_state(args.state), check=args.check)
    if args.report:
        atomic_json(args.report, report)
        print(f"Report: {args.report}")
    else:
        print(json.dumps(report, indent=2, ensure_ascii=False))
    print("Result:", report["mode"], report["counts"],
          "submitted:", report.get("submitted", 0), "XRefs: 0")
    if report["mode"] == "apply_aborted_preflight":
        return 1
    return int(any(key in report["counts"]
                   for key in ("api_error", "blocked_identity_mismatch",
                               "request_error_uncertain")))


if __name__ == "__main__":
    raise SystemExit(main())
