#!/usr/bin/env python3
"""One-shot, bounded, read-only Shoko AniDB episode title/details audit.

No /File enumeration, no /Anime walk, no metadata refresh, no link, no timer.
Only explicit AniDB work IDs are inspected. All Shoko API reads use a local
connection or an HTTPS URL with an API key in SHOKO_API_KEY.

  python3 episode_detail_probe.py --ids 10691,17477,19402,13831,16917,8925,15144,12693 \
    --output /root/shoko-episode-details.json
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from shoko_reconcile import ShokoAPI

DEFAULT_IDS = "10691,17477,19402,13831,16917,8925,15144,12693"
ANIDB_FIELDS = ("ID", "EpisodeID", "EpisodeNumber", "Number", "Type",
                "Title", "Titles", "Name", "NameEN", "EnglishTitle",
                "RomajiTitle", "EpisodeTitle", "Description", "AirDate",
                "Length", "Duration")


def parse_ids(text: str):
    raw = [segment.strip() for segment in str(text).split(",") if segment.strip()]
    ids = []
    for segment in raw:
        if not segment.isascii() or not segment.isdecimal() or int(segment) < 1:
            raise ValueError(f"Not a positive decimal AniDB ID: {segment!r}")
        aid = int(segment)
        if aid not in ids:
            ids.append(aid)
    return ids


def shorten(value, *, limit=350, depth=2):
    """Small structured extract; avoid huge blobs and arbitrary nested records."""
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    if isinstance(value, str):
        return value[:limit]
    if depth <= 0:
        return str(value)[:limit]
    if isinstance(value, list):
        return [shorten(v, limit=limit, depth=depth - 1) for v in value[:10]]
    if isinstance(value, dict):
        return {str(k)[:40]: shorten(v, limit=limit, depth=depth - 1)
                for k, v in list(value.items())[:12]}
    return str(value)[:limit]


def inspect(api, ids, *, max_ids=10):
    ids = list(dict.fromkeys(ids))
    if not ids or len(ids) > max_ids or any(type(aid) is not int or aid < 1 for aid in ids):
        raise ValueError(f"Supply 1..{max_ids} unique positive integer AniDB IDs")
    out = {"mode": "read_only_episode_details",
           "ids": ids, "works": [], "api_scope": {
               "explicit_aniDB_ids": len(ids),
               "full_file_scans": 0,
               "filesystem_media_walks": 0,
               "metadata_refresh_or_link_calls": 0}}
    for aid in ids:
        work = {"anidb_id": aid, "status": "missing"}
        try:
            series = api.local_series(aid)
            series_ids = (series or {}).get("IDs") or {}
            sid = series_ids.get("ID")
            if not sid or int(series_ids.get("AniDB") or -1) != aid:
                out["works"].append(work)
                continue
            work["shoko_series_id"] = sid = int(sid)
            entries = list(api.pages(f"/Series/{sid}/Episode", {
                "includeDataFrom": "AniDB",
                "includeMissing": "True",
                "includeUnaired": "True",
                "includeHidden": "True",
                "includeManuallyLinked": "True"}, size=500))
            work["status"] = "ready" if entries else "empty_episode_inventory"
            work["episodes"] = []
            for record in entries:
                source = record.get("AniDB") or {}
                work["episodes"].append({
                    "shoko_episode_id": record.get("ID"),
                    "anidb": {key: shorten(source[key]) for key in ANIDB_FIELDS
                              if key in source},
                    "available_anidb_fields": list(source)[:45]})
        except Exception as exc:
            work["status"] = "api_error"
            work["error"] = f"{type(exc).__name__}: {str(exc)[:180]}"
        out["works"].append(work)
    return out


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ids", default=DEFAULT_IDS,
                        help="Up to ten exact AniDB work IDs, comma-separated")
    parser.add_argument("--max-ids", type=int, default=10)
    parser.add_argument("--url", default="http://127.0.0.1:8111")
    parser.add_argument("--output", default="/root/shoko-episode-details.json")
    args = parser.parse_args(argv)
    api_key = os.getenv("SHOKO_API_KEY")
    if not api_key:
        parser.error("SHOKO_API_KEY is required; key is never written to output")
    try:
        ids = parse_ids(args.ids)
        if len(ids) > args.max_ids or not ids:
            parser.error(f"Specify between 1 and {args.max_ids} IDs")
    except ValueError as exc:
        parser.error(str(exc))
    result = inspect(ShokoAPI(args.url, api_key), ids, max_ids=args.max_ids)
    path = Path(args.output)
    if path.is_relative_to(Path("/Anime")):
        parser.error("Never write probe output under /Anime")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8")
    path.chmod(0o600)
    print(f"Read-only: {len(ids)} AniDB works inspected, "
          f"{sum(w['status']=='ready' for w in result['works'])} locally available; "
          f"saved {path}. No /File scans or Shoko writes.")


if __name__ == "__main__":
    main()
