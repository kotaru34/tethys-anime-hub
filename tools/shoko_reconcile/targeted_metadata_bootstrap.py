#!/usr/bin/env python3
"""One-shot AniDB metadata bootstrap for SIX reviewed works (20 files).

No /File calls, no /Anime walk, no XRef links, no timers/retry loops.
Defaults to a read-only dry-run of six exact-ID Shoko lookups.

  python3 targeted_metadata_bootstrap.py --report /root/shoko-metadata-dry-run.json
  python3 targeted_metadata_bootstrap.py --apply \
      --confirm CREATE_6_ANIDB_WORKS \
      --report /root/shoko-metadata-requested.json
  # Run once after Shoko has processed queued metadata:
  python3 targeted_metadata_bootstrap.py --check \
      --report /root/shoko-metadata-episodes.json

The apply path uses Shoko's already-established endpoint:
POST /Series/AniDB/{id}/Refresh with createSeriesEntry=true,
downloadRelations=false, force=false.

Persistent attempt records and an exclusive lock guarantee that a later
invocation does not enqueue a duplicate refresh if Shoko hasn't yet created
the local series entry. Even a connection loss after dispatch is treated as
an uncertain attempt requiring review, never as an automatic retry.
"""
from __future__ import annotations

import argparse
from collections import Counter
from contextlib import contextmanager
import fcntl
import json
import os
from pathlib import Path
import tempfile
import time

from shoko_reconcile import ShokoAPI

MANIFEST = Path(__file__).with_name("targeted_metadata_20261115.json")
STATE = Path("/var/lib/shoko-reconcile/targeted-metadata-20261115.state.json")
EXPECTED_AIDS = (11143, 14397, 14570, 17640, 17862, 18865)
EXPECTED_FIDS = (
    2485, 2486, 2489, 2972, 2973, 3037, 3038, 3040,
    3333, 3334, 3335, 3336, 3337, 3338, 3339, 3340,
    3341, 3342, 3343, 3344,
)
MAX_EPISODES_PER_WORK = 200


def validate(manifest):
    if manifest.get("schema") != 1:
        raise ValueError("Expected schema 1")
    works = manifest.get("works")
    if not isinstance(works, list) or len(works) != 6:
        raise ValueError("Exactly six reviewed AniDB works are required")
    ids, fids = [], []
    for row in works:
        aid = row.get("anidb_id")
        files = row.get("expected_file_ids")
        episodes = row.get("expected_episode_numbers")
        if (type(aid) is not int or aid < 1
                or not isinstance(row.get("title"), str) or not row["title"].strip()
                or not isinstance(files, list) or not files
                or any(type(n) is not int or n < 1 for n in files)
                or not isinstance(episodes, list) or not episodes
                or any(type(n) is not int or n < 1 for n in episodes)
                or len(set(files)) != len(files)
                or len(set(episodes)) != len(episodes)):
            raise ValueError(f"Invalid entry for AniDB {aid}")
        ids.append(aid)
        fids.extend(files)
    if tuple(sorted(ids)) != EXPECTED_AIDS:
        raise ValueError("Unexpected AniDB IDs; only approved six can be created")
    if tuple(sorted(fids)) != EXPECTED_FIDS:
        raise ValueError("Unexpected File IDs; approved set of twenty has changed")
    return works


def load_state(path=STATE):
    if not path.exists():
        return {"schema": 1, "attempts": {}}
    value = json.loads(path.read_text(encoding="utf-8"))
    if value.get("schema") != 1 or not isinstance(value.get("attempts"), dict):
        raise ValueError("Invalid persistent state; refusing metadata refresh")
    if not set(value["attempts"]).issubset({str(aid) for aid in EXPECTED_AIDS}):
        raise ValueError("Unknown attempts in state; refusing metadata refresh")
    return value


def atomic_json(path, data):
    """Write a private report/state atomically, never underneath /Anime."""
    path = Path(path)
    if path.is_relative_to(Path("/Anime")):
        raise ValueError("Refusing output inside the torrent media library")
    path.parent.mkdir(parents=True, exist_ok=True)
    filename = None
    try:
        with tempfile.NamedTemporaryFile(
                mode="w", encoding="utf-8", dir=path.parent,
                prefix=".shoko-metadata-", delete=False) as handle:
            filename = Path(handle.name)
            os.chmod(handle.name, 0o600)
            json.dump(data, handle, indent=2, ensure_ascii=False)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(filename, path)
    finally:
        if filename is not None:
            filename.unlink(missing_ok=True)


@contextmanager
def exclusive_state_lock(state_path):
    """Exclusive across CLI invocations, not just within one Python process."""
    lock_path = Path(str(state_path) + ".lock")
    if lock_path.is_relative_to(Path("/Anime")):
        raise ValueError("State lock must be outside /Anime")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o600)
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        yield
    finally:
        os.close(descriptor)


def episode_details(api, sid):
    """One series episode list, shared for the entire work. No file queries."""
    episodes = []
    for record in api.pages(f"/Series/{sid}/Episode", {
            "includeDataFrom": "AniDB", "includeMissing": "True",
            "includeUnaired": "True", "includeHidden": "True",
            "includeManuallyLinked": "True"}, size=500):
        source = record.get("AniDB") or {}
        kind = str(source.get("Type") or "")
        number = source.get("EpisodeNumber")
        if not kind or type(number) is not int or number < 1:
            continue
        episodes.append({
            "type": kind, "number": number,
            "anidb_episode_id": source.get("ID"),
            "title": str(source.get("Title") or "")[:240],
        })
        if len(episodes) > MAX_EPISODES_PER_WORK:
            raise ValueError("Episode inventory unexpectedly large for reviewed work")
    return sorted(episodes, key=lambda ep: (ep["type"], ep["number"]))


def preflight(api, manifest, state, *, include_episodes=False):
    """Exactly six GET lookups; optional episode lists only for present works."""
    works = validate(manifest)
    attempts = state["attempts"]
    rows = []
    for work in works:
        aid = work["anidb_id"]
        row = {"anidb_id": aid, "title": work["title"],
               "expected_file_ids": work["expected_file_ids"],
               "expected_episode_numbers": work["expected_episode_numbers"]}
        try:
            local = api.local_series(aid)
            if local is None:
                row["status"] = ("previously_requested_pending"
                                 if str(aid) in attempts else "missing")
                if str(aid) in attempts:
                    row["attempt"] = attempts[str(aid)]
            else:
                ids = local.get("IDs") or {}
                sid = int(ids.get("ID") or 0)
                actual = int(ids.get("AniDB") or 0)
                if not sid or actual != aid:
                    row.update(status="blocked_identity_mismatch",
                               reason="Shoko series IDs do not match requested AniDB work")
                else:
                    row.update(status="present", shoko_series_id=sid)
                    if include_episodes:
                        eps = episode_details(api, sid)
                        row["episodes"] = eps
                        row["ordinary_episode_numbers"] = sorted(
                            ep["number"] for ep in eps if ep["type"].casefold() in
                            {"episode", "normal"})
                        row["status"] = "present_ready" if eps else "present_without_episodes"
        except Exception as exc:
            row.update(status="api_error",
                       reason=f"{type(exc).__name__}: {str(exc)[:180]}")
        rows.append(row)
    return {"mode": "check" if include_episodes else "dry_run",
            "source": manifest.get("source"),
            "works": rows,
            "counts": dict(Counter(row["status"] for row in rows)),
            "scope": {"work_ids": len(works),
                      "expected_media_files": sum(len(w["expected_file_ids"]) for w in works),
                      "local_work_gets": len(works),
                      "episode_inventory_reads": sum("episodes" in row for row in rows),
                      "full_file_scans": 0, "media_walks": 0, "xref_writes": 0,
                      "periodic_jobs_created": 0}}


def request_missing(api, manifest, state, persist, *, pause_seconds=2,
                    sleep=time.sleep, now=time.time):
    """At most six POST requests, each durably recorded *before* dispatch."""
    report = preflight(api, manifest, state)
    if any(row["status"] in {"api_error", "blocked_identity_mismatch"}
           for row in report["works"]):
        report["mode"] = "apply_aborted_failed_preflight"
        report["requests_submitted"] = 0
        return report
    report["mode"] = "apply"
    report["requests_submitted"] = 0
    report["request_errors"] = 0
    attempted_count = 0
    for row in report["works"]:
        if row["status"] != "missing":
            continue
        aid = row["anidb_id"]
        if attempted_count:
            sleep(max(0, pause_seconds))
        key = str(aid)
        # The state write precedes the network request: if the process dies
        # or times out after server acceptance, later runs never re-enqueue.
        state["attempts"][key] = {
            "attempted_at_epoch": int(now()), "outcome": "dispatch_uncertain"}
        persist(state)
        attempted_count += 1
        try:
            api.refresh_series(aid)
        except Exception as exc:
            state["attempts"][key]["outcome"] = "request_error_uncertain"
            persist(state)
            row.update(status="request_error_uncertain",
                       reason=f"{type(exc).__name__}: {str(exc)[:180]}")
            report["request_errors"] += 1
            # A transport or rate-limit failure should halt this one-shot.
            break
        else:
            state["attempts"][key]["outcome"] = "requested"
            persist(state)
            row["status"] = "requested"
            report["requests_submitted"] += 1
    report["counts"] = dict(Counter(row["status"] for row in report["works"]))
    report["scope"]["targeted_metadata_posts"] = attempted_count
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=MANIFEST)
    parser.add_argument("--state", type=Path, default=STATE)
    parser.add_argument("--url", default="http://127.0.0.1:8111")
    parser.add_argument("--report", type=Path)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--confirm", default="")
    args = parser.parse_args(argv)
    if args.apply and args.check:
        parser.error("Choose either --apply or --check")
    if args.apply and args.confirm != "CREATE_6_ANIDB_WORKS":
        parser.error("Metadata creation requires --confirm CREATE_6_ANIDB_WORKS")
    key = os.getenv("SHOKO_API_KEY")
    if not key:
        parser.error("SHOKO_API_KEY is required; it is never printed")
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    validate(manifest)
    api = ShokoAPI(args.url, key)
    if args.apply:
        try:
            with exclusive_state_lock(args.state):
                state = load_state(args.state)
                report = request_missing(api, manifest, state,
                                         persist=lambda x: atomic_json(args.state, x))
        except BlockingIOError:
            parser.error("Another targeted metadata bootstrap is already running")
    else:
        report = preflight(api, manifest, load_state(args.state),
                           include_episodes=args.check)
    if args.report:
        atomic_json(args.report, report)
        print("Report:", args.report)
    else:
        print(json.dumps(report, indent=2, ensure_ascii=False))
    print("Result:", report["mode"], report["counts"],
          "requested:", report.get("requests_submitted", 0),
          "Shoko XRefs written: 0")
    return int(bool(
        any(key in report["counts"] for key in (
            "api_error", "blocked_identity_mismatch", "request_error_uncertain"))
        or report["mode"].startswith("apply_aborted")))


if __name__ == "__main__":
    raise SystemExit(main())
