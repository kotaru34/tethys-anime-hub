#!/usr/bin/env python3
"""Read-only verification of proposed Shoko Manual Links against actual XRefs.

Usage:
    python3 verify_links.py /root/shoko-sample-9.json /root/shoko-sample-24.json

Requires SHOKO_API_KEY. Never writes to Shoko or to the media library.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys

from shoko_reconcile import ShokoAPI, _series_id_from_api


def expected_from_plans(paths):
    expected = {}
    for path in paths:
        plan = json.loads(Path(path).read_text(encoding="utf8"))
        if plan.get("version") != 2:
            raise ValueError(f"{path}: expected a version-2 plan")
        for group in plan.get("groups", []):
            for row in group.get("files", []):
                if row.get("mode") in ("review", "episode_review", "extra"):
                    continue
                if not row.get("target_anidb_id") or not row.get("episode"):
                    continue
                fid = int(row["file_id"])
                target = (int(row["target_anidb_id"]), str(row["episode_type"]),
                          int(row["episode"]), str(row["path"]))
                if fid in expected and expected[fid] != target:
                    raise ValueError(f"Conflicting plans for Shoko file {fid}")
                expected[fid] = target
    if not expected:
        raise ValueError("No eligible file links in supplied plans")
    return expected


def _episode_index(api, sid):
    """Build (type, episode-number) -> local episode ID set from actual Shoko metadata."""
    index = {}
    for record in api.pages(f"/Series/{sid}/Episode", {
            "includeDataFrom": "AniDB", "includeMissing": "True",
            "includeUnaired": "True", "includeHidden": "True",
            "includeManuallyLinked": "True"}):
        anidb = record.get("AniDB") or {}
        kind = str(anidb.get("Type", "")).casefold()
        if kind in ("normal", "episode"):
            kind = "Episode"
        elif kind in ("special", "ova", "ona"):
            kind = "Special"
        elif kind in ("credits", "trailer", "parody", "other"):
            kind = kind.title()
        else:
            continue
        number = anidb.get("EpisodeNumber")
        eid = (record.get("IDs") or {}).get("ID")
        if isinstance(number, int) and isinstance(eid, int):
            index.setdefault((kind, number), set()).add(eid)
    return index


def verify(api, expected, *, printer=print):
    """Return (passed, total). A PASS requires one exact XRef and no extra XRefs."""
    passed = 0
    series_cache = {}
    episode_cache = {}
    for fid, (aid, kind, ep, path) in expected.items():
        try:
            record = api.request("GET", f"/File/{fid}", {"include": "XRefs"})
            if not isinstance(record, dict) or int(record.get("ID", -1)) != fid:
                raise ValueError("File missing or unexpected File ID")
            locations = {loc.get("RelativePath") for loc in record.get("Locations") or []}
            if path not in locations:
                raise ValueError("Original file path no longer matches")
            if aid not in series_cache:
                series = api.local_series(aid)
                sid = _series_id_from_api(series)
                if not sid:
                    raise ValueError(f"AniDB {aid} has no local Shoko series")
                actual_anidb = (series.get("IDs") or {}).get("AniDB")
                if actual_anidb is not None and int(actual_anidb) != aid:
                    raise ValueError(f"Shoko series has unexpected AniDB ID {actual_anidb}")
                series_cache[aid] = sid
            sid = series_cache[aid]
            if sid not in episode_cache:
                episode_cache[sid] = _episode_index(api, sid)
            target_kind = "Episode" if kind == "Movie" else kind
            episode_ids = episode_cache[sid].get((target_kind, ep), set())
            if len(episode_ids) != 1:
                raise ValueError(f"Expected exactly one metadata episode, got {sorted(episode_ids)}")
            expected_eid = next(iter(episode_ids))
            refs = [
                (int(ref["SeriesID"]["AniDB"]), x.get("ID"), x.get("Source"))
                for ref in record.get("SeriesIDs") or []
                for x in ref.get("EpisodeIDs") or []
            ]
            good = [ref for ref in refs if ref[0] == aid and ref[1] == expected_eid]
            if len(good) != 1 or len(refs) != 1:
                raise ValueError(f"XRef mismatch/extra references: {refs!r}, expected AniDB {aid} episode ID {expected_eid}")
            passed += 1
            printer(f"PASS File {fid} -> AniDB {aid} {kind}={ep} (source={good[0][2]})")
        except Exception as ex:
            printer(f"REVIEW File {fid} -> AniDB {aid} {kind}={ep}: {ex}")
    printer(f"\nVERIFIED: {passed}/{len(expected)}")
    return passed, len(expected)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("plans", nargs="+", help="Previously reviewed sample-plan JSON files")
    parser.add_argument("--url", default=os.getenv("SHOKO_URL", "http://127.0.0.1:8111"))
    args = parser.parse_args(argv)
    key = os.environ.get("SHOKO_API_KEY")
    if not key:
        parser.error("SHOKO_API_KEY not set")
    expected = expected_from_plans(args.plans)
    api = ShokoAPI(args.url, key)
    passed, total = verify(api, expected)
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())
