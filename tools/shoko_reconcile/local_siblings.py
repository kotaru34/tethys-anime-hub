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


def sibling_work_evidence(index, group, row):
    """Return (AniDB work ID, independent episode count), or None.

    This is the same evidence check for both initial promotion and the
    final apply boundary. It never trusts a previously saved count alone.
    """
    if group.get("mixed_season_source"):
        return None
    rel = str(row.get("path") or "")
    folder = _path_key(rel)
    if folder is None:
        return None
    info = classify_episode(rel, group=group.get("folder") or "")
    if (info.category != "Episode" or not isinstance(info.number, int)
            or info.number <= 0 or row.get("episode_type") != "Episode"
            or row.get("episode") != info.number):
        return None
    if row.get("source_episode") is not None and row["source_episode"] != info.number:
        return None
    evidence = index.get(folder)
    if not evidence or len(evidence["work_ids"]) != 1:
        return None
    aid = next(iter(evidence["work_ids"]))
    if any(anchor[3] != info.season for anchor in evidence["anchors"]):
        return None
    anchors = [a for a in evidence["anchors"] if a[1] == aid and a[3] == info.season]
    if len({a[0] for a in anchors}) < 2:
        return None
    distinct_episode_count = len({a[2] for a in anchors})
    if distinct_episode_count < 2:
        return None
    return aid, distinct_episode_count


def promote_linked_siblings(api, plan, eligible, *, reference=None):
    """Upgrade only fresh, stable unknown E-numbered files with strong anchors.

    Return count promoted to sibling_consensus. Real episode existence and
    file path remain independently checked in shoko_reconcile.apply().
    """
    if reference is None:
        reference = sibling_index(api)
    promoted = 0
    for group in plan.get("groups", []):
        for row in group.get("files", []):
            if int(row["file_id"]) not in eligible:
                continue
            if row.get("mode") in ("approved_release", "approved_file_override",
                                    "approved_override", "public_crosswalk",
                                    "nested_exact_work", "prior_exact_title"):
                continue
            proof = sibling_work_evidence(reference, group, row)
            if proof is None:
                continue
            aid, count = proof
            # A different work already independently chosen needs review.
            existing_aid = row.get("target_anidb_id")
            if existing_aid and int(existing_aid) != aid:
                continue
            row["target_anidb_id"] = aid
            row["mode"] = "sibling_consensus"
            row["source_episode"] = row["episode"]
            row["sibling_evidence_count"] = count
            row["reason"] = "two or more separately numbered Shoko-linked sibling episodes in exact directory"
            promoted += 1
    return promoted

def demote_nonexistent_sibling_episodes(api, plan, *, reference=None):
    """Reject sibling E-number guesses not actually present in that AniDB work.

    This prevents an E13 OVA in a 12-episode TV and an absolute E14..26 in
    a 13-episode season from being counted as valid sibling links.
    A separate verified-season-split pass may first redirect E14..26 to S2.
    """
    available_cache = {}
    demoted = 0
    for group in plan.get("groups", []):
        for row in group.get("files", []):
            if row.get("mode") != "sibling_consensus":
                continue
            aid = row.get("target_anidb_id")
            ep = row.get("episode")
            if not isinstance(aid, int) or not isinstance(ep, int):
                continue
            info = classify_episode(row.get("path") or "", group=group.get("folder") or "")
            invalid = info.category != "Episode" or info.number != ep
            if aid not in available_cache:
                series = api.local_series(aid)
                ids = (series or {}).get("IDs") or {}
                sid = ids.get("ID")
                if sid and int(ids.get("AniDB") or -1) == aid:
                    available_cache[aid] = api.available_episodes(int(sid))
                else:
                    available_cache[aid] = None
            episodes = available_cache[aid]
            # If a local series is not ready yet, do not fabricate its
            # episode list. apply() will request metadata and defer.
            if episodes is not None and ("Episode", ep) not in episodes:
                invalid = True
            if invalid:
                row["target_anidb_id"] = None
                row["mode"] = "episode_review"
                row["reason"] = "sibling work has no matching normal AniDB episode; possible OVA/recap/sequel"
                demoted += 1
    return demoted
