#!/usr/bin/env python3
"""Read-only one-shot snapshot of Shoko's *currently* unrecognized files.

Scope: one GET /File?include_only=Unrecognized&pageSize=100&page=1.
No /Anime walk, file rehash, metadata refresh, XRef link, or background timer.

Optional --audit-next19 requests only 19 explicitly reviewed File IDs
through GET /File/{id}. Those details are *diagnostics*, not proof that a
previously unrecognized file is now linked correctly.

    python3 current_unknown_snapshot.py --audit-next19 \
       --output /root/shoko-current-unknown-48.json
"""
from __future__ import annotations

import argparse
from collections import Counter
import json
import os
from pathlib import Path, PurePosixPath
import re
import tempfile

from shoko_reconcile import ShokoAPI

# Pin original 58 IDs from operator-provided shoko-reviewed-58-proposals.json,
# before the 15+19 one-shot XRef batches. IDs, not fuzzy title guesses.
BASELINE_IDS = frozenset((
    2253,2383,2384,2485,2486,2489,2742,2850,2909,2955,2957,
    2972,2973,2993,2994,2995,2997,2999,3005,3007,3008,3009,
    3016,3017,3018,3020,3023,3037,3038,3040,3139,3142,
    3146,3151,3152,3154,3206,3209,3213,3222,3321,
    3333,3334,3335,3336,3337,3338,3339,3340,3341,3342,
    3343,3344,3345,3346,3347,3350,3374
))
NEXT19 = Path(__file__).with_name("manual_xrefs_next19_20261115.json")
DATE_A_LIVE = re.compile(r"(?i)\bdate[\s._-]*a[\s._-]*live\b")
MATCH_KEYS = re.compile(r"(?i)(xref|cross.ref|episode|series|anidb|mapping|link|ids\b)")
MAX_UNRECOGNIZED = 100


def limited(value, depth=3):
    """Bound memory/size of individual inspected metadata nodes."""
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value[:500] if isinstance(value, str) else value
    if depth <= 0:
        return "<nested>"
    if isinstance(value, list):
        return [limited(item, depth - 1) for item in value[:60]]
    if isinstance(value, dict):
        return {str(k): limited(v, depth - 1)
                for k, v in list(value.items())[:40]}
    return str(value)[:100]


def snapshot(api, *, max_files=MAX_UNRECOGNIZED):
    if type(max_files) is not int or not 1 <= max_files <= MAX_UNRECOGNIZED:
        raise ValueError("max_files must be between 1 and 100")
    page = api.request("GET", "/File", {
        "include_only": "Unrecognized", "pageSize": max_files, "page": 1})
    if (not isinstance(page, dict) or type(page.get("Total")) is not int
            or not isinstance(page.get("List"), list)):
        raise ValueError("Unexpected Shoko unrecognized ListResult")
    total = page["Total"]
    if total > max_files:
        raise ValueError(f"Shoko reports {total} unknown files, over the "
                         f"{max_files}-file one-page safety cap; no partial report generated")
    rows = page["List"]
    if total != len(rows):
        raise ValueError(f"Shoko count changed during snapshot: Total={total}, "
                         f"returned={len(rows)}. Retry later, not a partial report")
    files = []
    ids = set()
    for raw in rows:
        fid = raw.get("ID")
        if type(fid) is not int or fid < 1 or fid in ids:
            raise ValueError("Invalid or duplicate File ID in Shoko snapshot")
        ids.add(fid)
        paths = [str(loc.get("RelativePath") or "")
                 for loc in (raw.get("Locations") or []) if isinstance(loc, dict)]
        primary = paths[0] if paths else ""
        head = PurePosixPath(primary).parts
        folder = head[0] if len(head) > 1 else "__missing_folder__"
        is_date = bool(DATE_A_LIVE.search(primary))
        files.append({
            "file_id": fid,
            "path": primary,
            "relative_paths": paths[:6],
            "folder": folder,
            "cohort": "original_58" if fid in BASELINE_IDS else "new_since_original_58",
            "date_a_live_filename_hint": is_date,
        })
    files.sort(key=lambda x: (x["cohort"], x["folder"].casefold(), x["path"].casefold()))
    cohorts = Counter(f["cohort"] for f in files)
    folders = Counter(f["folder"] for f in files)
    date = Counter(
        ("original_58" if f["file_id"] in BASELINE_IDS else "new_since_original_58")
        for f in files if f["date_a_live_filename_hint"])
    return {
        "mode": "read_only_unrecognized_snapshot",
        "baseline": "58 unrecognized File IDs in shoko-reviewed-58-proposals.json",
        "total_unrecognized": total,
        "cohorts": dict(cohorts),
        "date_a_live_filename_hints_by_cohort": dict(date),
        "folders": dict(folders),
        "files": files,
        "api_scope": {
            "unrecognized_file_list_requests": 1,
            "full_library_file_lists": 0,
            "anime_filesystem_walks": 0,
            "metadata_refresh_requests": 0,
            "xref_writes": 0,
        },
    }


def audit_prior_next19(api, current_ids, manifest):
    """Targeted read-only direct File-ID inspection; never call linking APIs."""
    entries = manifest.get("entries")
    if (manifest.get("schema") != 1 or not isinstance(entries, list)
            or len(entries) != 19):
        raise ValueError("Expected the exact 19-file previous manual batch")
    ids = [e.get("file_id") for e in entries]
    if len(set(ids)) != 19 or any(type(x) is not int or x < 1 for x in ids):
        raise ValueError("Invalid previous 19-file audit manifest")
    rows = []
    for entry in entries:
        fid = entry["file_id"]
        summary = {
            "file_id": fid,
            "prior_intended_anidb_id": entry["anidb_id"],
            "prior_intended_type": entry["type"],
            "prior_intended_episode": entry["episode"],
            "still_unrecognized": fid in current_ids,
        }
        try:
            result = api.request("GET", f"/File/{fid}", {"includeXRefs": "true"})
            if not isinstance(result, dict):
                summary.update(status="unexpected_file_response")
            else:
                summary["status"] = "record_returned"
                summary["file_response_keys"] = list(result.keys())[:50]
                summary["cross_reference_fields"] = {
                    k: limited(v) for k, v in result.items()
                    if MATCH_KEYS.search(k)
                }
                summary["locations"] = [
                    x.get("RelativePath") for x in result.get("Locations") or []
                    if isinstance(x, dict)
                ][:5]
        except Exception as exc:
            summary.update(status="api_error", error=f"{type(exc).__name__}: {str(exc)[:220]}")
        rows.append(summary)
    return {
        "scope": "19 exact File-ID GETs for prior batch; not proof of correct linking",
        "checked": len(rows),
        "previous_batch_file_ids": ids,
        "records": rows,
        "interpretation_warning": (
            "A File ID being absent from Unrecognized alone does not establish "
            "a correct AniDB XRef. Inspect returned reference fields and compare "
            "against the pinned previous work/type/episode identities."),
    }


def write_private(path, data):
    path = Path(path)
    if path.is_relative_to(Path("/Anime")):
        raise ValueError("Cannot write under torrent library /Anime")
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = None
    try:
        with tempfile.NamedTemporaryFile(
                mode="w", encoding="utf-8", dir=path.parent,
                prefix=".shoko-snapshot-", delete=False) as f:
            tmp = Path(f.name)
            os.chmod(f.name, 0o600)
            json.dump(data, f, indent=2, ensure_ascii=False)
            f.write("\n")
        os.replace(tmp, path)
    finally:
        if tmp is not None:
            tmp.unlink(missing_ok=True)


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--url", default="http://127.0.0.1:8111")
    p.add_argument("--output", type=Path, default=Path("/root/shoko-current-unknown-48.json"))
    p.add_argument("--audit-next19", action="store_true",
                   help="Additionally GET only the 19 prior manually reviewed file IDs")
    args = p.parse_args(argv)
    key = os.getenv("SHOKO_API_KEY")
    if not key:
        p.error("SHOKO_API_KEY environment variable required; it is never printed")
    api = ShokoAPI(args.url, key)
    report = snapshot(api)
    if args.audit_next19:
        manifest = json.loads(NEXT19.read_text(encoding="utf-8"))
        report["prior_next19_file_audit"] = audit_prior_next19(
            api, {x["file_id"] for x in report["files"]}, manifest)
        report["api_scope"]["targeted_prior_file_reads"] = 19
    else:
        report["api_scope"]["targeted_prior_file_reads"] = 0
    write_private(args.output, report)
    print(f"Report: {args.output}")
    print("Result: read_only_snapshot", report["total_unrecognized"],
          "cohorts:", report["cohorts"],
          "Date A Live name hints:", report["date_a_live_filename_hints_by_cohort"],
          "XRef writes: 0")


if __name__ == "__main__":
    main()
