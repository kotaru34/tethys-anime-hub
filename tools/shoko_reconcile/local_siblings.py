"""Conservative local-work inference from already indexed Shoko siblings.

This module never writes to Shoko or /Anime. It only promotes a fresh,
still-unrecognized E-numbered file if two *different numbered episodes* in
the exact same directory are already linked by Shoko to one AniDB work.

It intentionally refuses nested series, mixed seasons, specials, movies,
weak/contradictory per-file title proposals and duplicate-encode-only anchors.
"""
from __future__ import annotations

from collections import defaultdict
from pathlib import PurePosixPath

from matching import classify_episode


def _path_key(rel):
    pure = PurePosixPath(str(rel or "").replace("\\", "/"))
    if not rel or pure.is_absolute() or ".." in pure.parts or len(pure.parts) < 2:
        return None
    return pure.parent.as_posix()


def sibling_index(api):
    """Index recognized file-level XRefs per *exact* parent directory."""
    index = defaultdict(lambda: {"work_ids": set(), "anchors": []})
    for record in api.pages("/File", {"include": "XRefs"}):
        fid = record.get("ID")
        refs = record.get("SeriesIDs") or []
        if not refs:
            continue
        work_ids = set()
        single = None
        for ref in refs:
            series_id = ref.get("SeriesID") or {}
            aid = series_id.get("AniDB") if isinstance(series_id, dict) else None
            if aid is not None:
                work_ids.add(int(aid))
                episode_refs = ref.get("EpisodeIDs") or []
                if len(refs) == 1 and len(episode_refs) == 1:
                    single = int(aid)
        for location in record.get("Locations") or []:
            rel = str(location.get("RelativePath") or "")
            key = _path_key(rel)
            if key is None:
                continue
            entry = index[key]
            entry["work_ids"].update(work_ids)
            if single is None:
                continue
            # Filename numbering must be independent evidence: never rely on
            # a guessed number inside a bonus file or a multi-episode file.
            info = classify_episode(rel, group=PurePosixPath(rel).parts[0])
            if info.category != "Episode" or not isinstance(info.number, int) or info.number <= 0:
                continue
            entry["anchors"].append((fid, single, info.number, info.season))
    return index


def promote_linked_siblings(api, plan, eligible):
    """Upgrade only fresh, stable unknown E-numbered files with strong anchors.

    Return count promoted to sibling_consensus. Real episode existence and
    file path remain independently checked in shoko_reconcile.apply().
    """
    reference = sibling_index(api)
    promoted = 0
    for group in plan.get("groups", []):
        if group.get("mixed_season_source"):
            continue
        for row in group.get("files", []):
            if int(row["file_id"]) not in eligible:
                continue
            if row.get("mode") in ("approved_release", "approved_file_override",
                                    "approved_override", "public_crosswalk",
                                    "nested_exact_work", "prior_exact_title"):
                continue
            rel = str(row.get("path") or "")
            folder = _path_key(rel)
            if folder is None:
                continue
            info = classify_episode(rel, group=group.get("folder") or "")
            if (info.category != "Episode" or not isinstance(info.number, int)
                    or info.number <= 0 or row.get("episode_type") != "Episode"
                    or row.get("episode") != info.number):
                continue
            evidence = reference.get(folder)
            if not evidence or len(evidence["work_ids"]) != 1:
                continue
            aid = next(iter(evidence["work_ids"]))
            anchors = [a for a in evidence["anchors"] if a[1] == aid and a[3] == info.season]
            # Reject any other season in this folder, even if that file would
            # otherwise count as a harmless additional recognized episode.
            if any(a[3] != info.season for a in evidence["anchors"]):
                continue
            if len({a[0] for a in anchors}) < 2 or len({a[2] for a in anchors}) < 2:
                continue
            # If a separate title matcher chose a *different* work, the
            # conflict needs review rather than overwriting its guess.
            existing_aid = row.get("target_anidb_id")
            if existing_aid and int(existing_aid) != aid:
                continue
            row["target_anidb_id"] = aid
            row["mode"] = "sibling_consensus"
            row["source_episode"] = info.number
            row["sibling_evidence_count"] = len({a[2] for a in anchors})
            row["reason"] = "two or more separately numbered Shoko-linked sibling episodes in exact directory"
            promoted += 1
    return promoted
