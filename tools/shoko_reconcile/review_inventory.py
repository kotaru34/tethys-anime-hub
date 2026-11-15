#!/usr/bin/env python3
"""One-shot, READ-ONLY local AniDB inventory for unresolved Shoko review files.

Unlike the Reconciler, this tool does NOT enumerate /File, walk /Anime, refresh
metadata, link files or start a timer. It reads an existing private plan and
makes at most two targeted read-only Shoko requests per distinct AniDB work,
plus a bounded list of title searches for missing standalone OVA works.

Example:
  SHOKO_API_KEY=... python3 review_inventory.py \
    --plan /var/lib/shoko-reconcile/realtime-plan.review.json \
    --ids 11184,11844,14206,15807 --output /root/shoko-review-inventory.json
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from shoko_reconcile import ShokoAPI

SEARCH_TITLES = (
    "Jaku-Chara Tomozaki-kun OVA",
    "Kono Subarashii Sekai ni Shukufuku wo! 3 Bonus Stage",
    "High School DxD BorN Specials",
    "Kono Yo no Hate de Koi wo Utau Shoujo YU-NO Mugen no Heiretsu Sekai",
    "Yuusha, Yamemasu OVA",
    "Ore wo Suki nano wa Omae dake ka yo OVA",
    "Goblin Slayer Adventure Sheet",
)


def plan_work_ids(plan):
    """Only exact-selected and top-scoring candidate IDs, not all fuzzy hits."""
    aids = set()
    for group in plan.get("groups") or []:
        selected = group.get("selected_anidb_id")
        if isinstance(selected, int) and selected > 0:
            aids.add(selected)
        for candidate in group.get("candidates") or []:
            aid = candidate.get("anidb_id")
            if (isinstance(aid, int) and aid > 0
                    and float(candidate.get("score") or 0) >= 0.98):
                aids.add(aid)
    return aids


def inspect(api, plan, *, extra_ids=(), searches=SEARCH_TITLES,
            max_ids=32, max_searches=8):
    if plan.get("version") != 2 or not isinstance(plan.get("groups"), list):
        raise ValueError("Expected a version-2 review plan")
    ids = plan_work_ids(plan) | {int(aid) for aid in extra_ids}
    if len(ids) > max_ids:
        raise ValueError(f"{len(ids)} candidate AniDB IDs exceeds cap {max_ids}; "
                         "use a smaller review plan or increase --max-ids explicitly")
    if len(searches) > max_searches:
        raise ValueError(f"Search cap exceeded: {len(searches)} > {max_searches}")
    result = {
        "mode": "read_only_shoko_review_inventory",
        "source_unrecognized": plan.get("source_unrecognized_at_scan"),
        "planned_ids": sorted(ids),
        "local_work_inventory": [],
        "title_search": {},
    }
    for aid in sorted(ids):
        record = {"anidb_id": aid}
        try:
            series = api.local_series(aid)
            series_ids = (series or {}).get("IDs") or {}
            sid = series_ids.get("ID")
            if not sid or int(series_ids.get("AniDB") or -1) != aid:
                record["status"] = "not_in_local_shoko"
            else:
                sid = int(sid)
                eps = api.available_episodes(sid)
                record.update({
                    "status": "ready" if eps else "episode_inventory_empty",
                    "shoko_series_id": sid,
                    "episodes": [
                        {"type": kind, "number": number}
                        for kind, number in sorted(eps, key=lambda x: (x[0], x[1]))
                    ],
                })
        except Exception as exc:
            record["status"] = "api_error"
            record["error"] = f"{type(exc).__name__}: {str(exc)[:180]}"
        result["local_work_inventory"].append(record)
    for query in searches:
        try:
            hits = api.anime_search(query)
            # Compact diagnostic metadata; no full title dumps or extra lookups.
            result["title_search"][query] = [{
                "anidb_id": hit.get("ID"),
                "title": hit.get("Title"),
                "type": hit.get("Type"),
                "shoko_series_id": hit.get("ShokoID"),
                "aliases": [
                    t.get("Name") for t in hit.get("Titles", [])
                    if isinstance(t, dict) and t.get("Name")
                ][:12],
            } for hit in hits[:12]]
        except Exception as exc:
            result["title_search"][query] = {"error":
                f"{type(exc).__name__}: {str(exc)[:180]}"}
    result["api_scope"] = {
        "distinct_local_work_ids": len(ids),
        "targeted_title_queries": len(searches),
        "full_file_scan_calls": 0,
        "filesystem_media_walks": 0,
        "write_or_refresh_calls": 0,
    }
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan",
        default="/var/lib/shoko-reconcile/realtime-plan.review.json")
    parser.add_argument("--output", default="/root/shoko-review-inventory.json")
    parser.add_argument("--url", default="http://127.0.0.1:8111")
    parser.add_argument("--ids", default="",
        help="Optional extra AniDB IDs (comma-separated; no fuzzy expansion)")
    parser.add_argument("--max-ids", type=int, default=32)
    parser.add_argument("--max-searches", type=int, default=8)
    parser.add_argument("--no-search", action="store_true")
    args = parser.parse_args(argv)
    key = os.getenv("SHOKO_API_KEY")
    if not key:
        parser.error("Export SHOKO_API_KEY in this shell; the value is never printed")
    plan = json.loads(Path(args.plan).read_text(encoding="utf-8"))
    extra_ids = [int(v.strip()) for v in args.ids.split(",") if v.strip()]
    result = inspect(ShokoAPI(args.url, key), plan, extra_ids=extra_ids,
                     searches=() if args.no_search else SEARCH_TITLES,
                     max_ids=args.max_ids, max_searches=args.max_searches)
    output = Path(args.output)
    if output.is_relative_to(Path("/Anime")):
        parser.error("Refusing to write any results under /Anime")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n",
                      encoding="utf-8")
    output.chmod(0o600)
    print(f"Read-only inventory saved to {output}: "
          f"{len(result['local_work_inventory'])} target AniDB IDs and "
          f"{len(result['title_search'])} title searches; no /File scan or writes to Shoko")


if __name__ == "__main__":
    main()
