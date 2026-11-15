#!/usr/bin/env python3
"""One-shot, operator-approved Shoko XRef batch. Dry-run is the default.

The manifest contains only individually curated File ID + exact relative path
+ AniDB work + AniDB episode ID/type/number/title. Do not run for generic
reconciliation. Never touches torrent files or /Anime.

Dry-run:
  SHOKO_API_KEY=... python3 manual_review_batch.py \
    --report /root/shoko-manual-batch-check.json

Only after inspecting that report:
  SHOKO_API_KEY=... python3 manual_review_batch.py \
    --apply --confirm APPLY_SHOKO_XREFS_15 \
    --report /root/shoko-manual-batch-result.json

At most one existing unrecognized-file listing and one AniDB episode-inventory
read per distinct work. No new watchers, file walking or refresh requests.
"""
from __future__ import annotations

import argparse
import json
import os
from collections import Counter
from pathlib import Path

from shoko_reconcile import ShokoAPI

DEFAULT_MANIFEST = Path(__file__).with_name("manual_xrefs_20261115.json")
ALLOWED_KINDS = {"Episode", "Special", "Other"}


def validate_manifest(manifest):
    if manifest.get("schema") != 1 or not isinstance(manifest.get("entries"), list):
        raise ValueError("Expected a schema-1 manifest with entries")
    entries = manifest["entries"]
    if not 1 <= len(entries) <= 30:
        raise ValueError("Expected between 1 and 30 curated entries")
    seen_files, seen_episodes = set(), set()
    for row in entries:
        fid, aid, sid = (row.get(k) for k in
                         ("file_id", "anidb_id", "shoko_series_id"))
        number, eid = row.get("episode"), row.get("anidb_episode_id")
        if (any(type(x) is not int or x < 1
                for x in (fid, aid, sid, number, eid))
                or row.get("type") not in ALLOWED_KINDS
                or not isinstance(row.get("path"), str)
                or not row["path"] or row["path"].startswith("/")
                or ".." in Path(row["path"]).parts
                or not isinstance(row.get("title"), str)
                or not row["title"]):
            raise ValueError(f"Invalid entry for file ID {fid}")
        target = (aid, row["type"], number, eid)
        if fid in seen_files or target in seen_episodes:
            raise ValueError("Duplicate File ID or AniDB episode identity")
        seen_files.add(fid)
        seen_episodes.add(target)
    return entries


def _episode_index(api, sid):
    result = {}
    for record in api.pages(f"/Series/{sid}/Episode", {
            "includeDataFrom": "AniDB", "includeMissing": "True",
            "includeUnaired": "True", "includeHidden": "True",
            "includeManuallyLinked": "True"}, size=500):
        anidb = record.get("AniDB") or {}
        kind = str(anidb.get("Type") or "").casefold()
        if kind in ("normal", "episode"):
            kind = "Episode"
        elif kind in ("ova", "ona", "special"):
            kind = "Special"
        else:
            kind = kind.title()
        number = anidb.get("EpisodeNumber")
        if kind not in ALLOWED_KINDS or type(number) is not int or number < 1:
            continue
        key = kind, number
        result.setdefault(key, []).append({
            "anidb_episode_id": anidb.get("ID"),
            "title": anidb.get("Title")})
    return result


def preflight(api, manifest):
    """Read-only. Validate every pending row before ANY link can be sent."""
    entries = validate_manifest(manifest)
    unrecognized = {int(f["ID"]): f for f in api.unrecognized()}
    series_cache, episode_cache = {}, {}
    rows = []
    for entry in entries:
        file_id, aid = entry["file_id"], entry["anidb_id"]
        state = {"file_id": file_id, "anidb_id": aid,
                 "type": entry["type"], "episode": entry["episode"]}
        source = unrecognized.get(file_id)
        if source is None:
            state["status"] = "not_unrecognized_skip"
            rows.append(state)
            continue
        paths = {loc.get("RelativePath") for loc in source.get("Locations") or []}
        if entry["path"] not in paths:
            state.update(status="blocked", reason="exact_relative_path_changed")
            rows.append(state)
            continue
        if aid not in series_cache:
            series_cache[aid] = api.local_series(aid)
        series = series_cache[aid] or {}
        ids = series.get("IDs") or {}
        try:
            sid = int(ids.get("ID") or 0)
            actual_aid = int(ids.get("AniDB") or 0)
        except (ValueError, TypeError):
            sid = actual_aid = 0
        if (sid != entry["shoko_series_id"] or actual_aid != aid):
            state.update(status="blocked", reason="local_shoko_work_id_changed_or_missing")
            rows.append(state)
            continue
        if sid not in episode_cache:
            episode_cache[sid] = _episode_index(api, sid)
        actual = episode_cache[sid].get((entry["type"], entry["episode"]), [])
        matching = [candidate for candidate in actual
                    if (candidate["anidb_episode_id"] == entry["anidb_episode_id"]
                        and candidate["title"] == entry["title"])]
        if len(actual) != 1 or len(matching) != 1:
            state.update(status="blocked",
                         reason="anidb_episode_id_type_number_or_title_changed")
            rows.append(state)
            continue
        state.update(status="ready", shoko_series_id=sid,
                     anidb_episode_id=entry["anidb_episode_id"],
                     title=entry["title"])
        rows.append(state)
    counts = dict(Counter(row["status"] for row in rows))
    return {
        "mode": "dry_run",
        "source": manifest.get("source"),
        "counts": counts,
        "rows": rows,
        "api_scope": {
            "unrecognized_file_enumerations": 1,
            "distinct_anidb_work_reads": len(series_cache),
            "distinct_episode_inventory_reads": len(episode_cache),
            "media_walks": 0,
            "shoko_refresh_requests": 0,
        },
    }


def apply_batch(api, manifest):
    report = preflight(api, manifest)
    # Preflight is all-or-nothing for actionable entries. An already
    # recognized/missing ID is skipped safely, never force-linked.
    if report["counts"].get("blocked", 0):
        report["mode"] = "apply_aborted_preflight"
        report["submitted"] = 0
        return report
    report["mode"] = "apply"
    report["submitted"] = 0
    for row in report["rows"]:
        if row["status"] != "ready":
            continue
        try:
            api.link(row["file_id"], row["shoko_series_id"],
                     row["episode"], row["type"])
        except Exception as exc:
            row.update(status="write_failed", reason=f"{type(exc).__name__}: {str(exc)[:180]}")
            report["mode"] = "apply_partial_error"
            break
        else:
            row["status"] = "submitted"
            report["submitted"] += 1
    report["counts"] = dict(Counter(row["status"] for row in report["rows"]))
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--url", default="http://127.0.0.1:8111")
    parser.add_argument("--report", type=Path)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--confirm", default="")
    args = parser.parse_args(argv)
    if args.apply and args.confirm != "APPLY_SHOKO_XREFS_15":
        parser.error("Applying needs --confirm APPLY_SHOKO_XREFS_15")
    key = os.getenv("SHOKO_API_KEY")
    if not key:
        parser.error("Export SHOKO_API_KEY first (never printed or saved)")
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    validate_manifest(manifest)
    api = ShokoAPI(args.url, key)
    report = apply_batch(api, manifest) if args.apply else preflight(api, manifest)
    if args.report:
        if args.report.is_relative_to(Path("/Anime")):
            parser.error("Refusing to write a report under /Anime")
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n",
                               encoding="utf-8")
        args.report.chmod(0o600)
        print("Report:", args.report)
    else:
        print(json.dumps(report, indent=2, ensure_ascii=False))
    print("Result:", report["mode"], report["counts"],
          "submitted:", report.get("submitted", 0))
    return 1 if (report["counts"].get("blocked", 0)
                 or report["counts"].get("write_failed", 0)) else 0


if __name__ == "__main__":
    raise SystemExit(main())
