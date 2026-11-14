"""Independent, fail-closed proof for a complete TV batch with spaced romaji aliases.

A filename batch cannot be promoted by similarity alone. The *whole* work
title must be identical after removal of Latin word spacing (e.g. Konoyo vs
Kono Yo), exactly one AniDB TV identity must match, and Shoko must already
have the precise contiguous E01..EN episode inventory. No metadata creation,
filesystem reads, or guessing of cour offsets are performed here.
"""
from __future__ import annotations

from pathlib import PurePosixPath
import re

from matching import (classify_episode, clean_release_title, match_key,
                      season_hint, target_season_supported, type_hint)


def _compact_title(title):
    canonical = match_key(str(title or ""), strict=True)
    compact = canonical.replace(" ", "")
    # Only collapse spaces in full-length Latin/romaji names. Short titles,
    # symbols with semantic meanings and non-Latin scripts need exact review.
    if (len(compact) < 24 or not re.fullmatch(r"[a-z0-9]+", compact)
            or len(canonical.split()) < 3):
        return None
    return compact


def _aliases(candidate):
    for field in ("title", "matched_alias"):
        value = candidate.get(field)
        if isinstance(value, str):
            yield value
    for item in candidate.get("aliases") or []:
        if isinstance(item, str):
            yield item
    titles = candidate.get("Titles") or []
    if isinstance(titles, dict):
        titles = titles.values()
    for item in titles:
        if isinstance(item, str):
            yield item
        elif isinstance(item, dict):
            for name in ("Name", "Title", "Value", "Text"):
                value = item.get(name)
                if isinstance(value, str):
                    yield value


def unique_tv_work(group):
    folder = group.get("folder") or ""
    if (folder.startswith("__") or group.get("mixed_season_source")
            or type_hint(folder) is not None):
        return None
    release = clean_release_title(folder)
    key = _compact_title(release)
    if key is None:
        return None
    requested_season = season_hint(release)
    found = {}
    for candidate in group.get("candidates") or []:
        aid = candidate.get("anidb_id")
        if not isinstance(aid, int) or str(candidate.get("type") or "").casefold() not in {"tv", "tv series"}:
            continue
        candidate_season = candidate.get("season")
        if candidate_season is None:
            candidate_season = season_hint(str(candidate.get("title") or ""))
        if requested_season is None and candidate_season is not None and candidate_season > 1:
            continue
        if (requested_season is not None and candidate_season is not None
                and requested_season != candidate_season):
            continue
        # Match a full title, never just a franchise root or partial query.
        if not any(_compact_title(alias) == key for alias in _aliases(candidate)):
            continue
        found[aid] = candidate
    if len(found) != 1:
        return None
    return next(iter(found.values()))


def _batch_rows(group, eligible=None):
    folder = group.get("folder") or ""
    rows = []
    for row in group.get("files") or []:
        rel = str(row.get("path") or "")
        path = PurePosixPath(rel)
        if len(path.parts) != 2 or path.parts[0] != folder:
            return None
        info = classify_episode(rel, group=folder)
        if info.category != "Episode":
            # OVA, specials and extras are excluded from TV evidence and
            # cannot be promoted even if they share the title folder.
            continue
        if (not isinstance(info.number, int) or info.number <= 0
                or row.get("episode") != info.number
                or row.get("episode_type") != "Episode"
                or row.get("source_episode") not in (None, info.number)
                or row.get("mode") in {"approved_release", "approved_override",
                                       "approved_file_override", "nested_exact_work",
                                       "public_crosswalk", "prior_exact_title",
                                       "verified_second_season"}):
            return None
        if eligible is not None and int(row.get("file_id") or 0) not in eligible:
            return None
        rows.append((info.number, row))
    if len(rows) < 6:
        return None
    numbers = [number for number, _ in rows]
    if len(numbers) != len(set(numbers)):
        return None
    return rows


def _episodes(api, aid, cache):
    if aid not in cache:
        series = api.local_series(aid)
        ids = (series or {}).get("IDs") or {}
        if int(ids.get("AniDB") or -1) != aid or not ids.get("ID"):
            cache[aid] = None
        else:
            cache[aid] = api.available_episodes(int(ids["ID"]))
    return cache[aid]


def tv_batch_proof(api, group, *, eligible=None, cache=None):
    cache = {} if cache is None else cache
    candidate = unique_tv_work(group)
    if candidate is None:
        return None
    rows = _batch_rows(group, eligible)
    if not rows:
        return None
    aid = int(candidate["anidb_id"])
    if any(not target_season_supported(
            group, {**row, "target_anidb_id": aid, "mode": "strong_context"})
            for _, row in rows):
        return None
    episodes = _episodes(api, aid, cache)
    if not episodes:
        return None
    ordinary = {n for kind, n in episodes if kind == "Episode"}
    n = len(ordinary)
    numbers = {number for number, _ in rows}
    if not (6 <= n <= 26 and ordinary == set(range(1, n + 1))
            and numbers == ordinary):
        return None
    return aid, n, [row for _, row in rows]


def promote_verified_tv_batch(api, plan, eligible, *, diagnostics=None):
    """Promote a work only after full-title, season and live episode proof."""
    diagnostics = {} if diagnostics is None else diagnostics
    cache = {}
    promoted = 0
    for group in plan.get("groups") or []:
        if unique_tv_work(group) is None:
            continue
        diagnostics["exact_spaced_tv_groups"] = diagnostics.get("exact_spaced_tv_groups", 0) + 1
        proof = tv_batch_proof(api, group, eligible=eligible, cache=cache)
        if proof is None:
            diagnostics["incomplete_or_unverified_tv_groups"] = diagnostics.get(
                "incomplete_or_unverified_tv_groups", 0) + 1
            continue
        aid, count, rows = proof
        for row in rows:
            row["target_anidb_id"] = aid
            row["mode"] = "verified_tv_batch"
            row["verified_tv_episode_count"] = count
            row["reason"] = "unique full romaji TV title and Shoko verified complete AniDB E01..EN inventory"
            promoted += 1
        diagnostics["verified_tv_groups"] = diagnostics.get("verified_tv_groups", 0) + 1
    return promoted


def verify_tv_batch_row(api, group, row, *, cache=None):
    if row.get("mode") != "verified_tv_batch":
        return False
    aid = row.get("target_anidb_id")
    n = row.get("verified_tv_episode_count")
    if not isinstance(aid, int) or not isinstance(n, int):
        return False
    proof = tv_batch_proof(api, group, cache=cache)
    if not proof or proof[0] != aid or proof[1] != n:
        return False
    return any(r.get("file_id") == row.get("file_id") for r in proof[2])
