"""Conservative absolute-episode split across AniDB TV seasons.

Only when:
- Shoko has two separately numbered E-episode anchors for one S1 work
  in the SAME directory;
- that S1 work has 6..26 consecutive verified AniDB normal episodes;
- the same directory contains a contiguous block of >=3 normal episodes
  starting at the very next absolute number (N+1);
- live Shoko AniDB search returns exactly one separate anime work named
  '<full S1 title> 2nd Season';
- the target episode number is source-N.
The destination's own AniDB episode must still exist in apply(). No
file operations and no forced links to nonexistent episodes.
"""
from __future__ import annotations

from pathlib import PurePosixPath

from matching import classify_episode, clean_release_title, match_key, season_hint, type_hint
from local_siblings import sibling_work_evidence, sibling_index


def normal_episode_count(api, aid, cache):
    if aid not in cache:
        series = api.local_series(aid)
        ids = (series or {}).get("IDs") or {}
        if int(ids.get("AniDB") or -1) != aid or not ids.get("ID"):
            cache[aid] = None
        else:
            episodes = api.available_episodes(int(ids["ID"]))
            numbers = {v[1] for v in episodes if isinstance(v, tuple) and
                       len(v) == 2 and v[0] == "Episode" and isinstance(v[1], int)}
            maximum = max(numbers) if numbers else 0
            cache[aid] = (maximum if 6 <= maximum <= 26 and
                          numbers == set(range(1, maximum + 1)) else None)
    return cache[aid]


def _search_titles(item):
    """Full Shoko AniDB search names, including typed multilingual aliases."""
    title = item.get("Title")
    if isinstance(title, str):
        yield title
    titles = item.get("Titles") or []
    if isinstance(titles, dict):
        titles = list(titles.values())
    for value in titles:
        if isinstance(value, str):
            yield value
        elif isinstance(value, dict):
            for key in ("Title", "Text", "Value", "Name"):
                if isinstance(value.get(key), str):
                    yield value[key]


def second_season_id(api, base_title, original_aid, cache):
    key = match_key(base_title)
    if not key or season_hint(base_title) is not None or type_hint(base_title):
        return None
    cache_key = (key, original_aid)
    if cache_key not in cache:
        # Full exact names only: fuzzy rank, franchise root and year do not
        # establish a different season. Both common word orders are valid.
        queries = (base_title + " 2nd Season", base_title + " Season 2")
        accepted = {match_key(title) for title in queries}
        ids = set()
        for query in queries:
            for item in api.anime_search(query):
                if not item.get("ID"):
                    continue
                aid = int(item["ID"])
                if aid == original_aid:
                    continue
                media_type = str(item.get("Type") or "Unknown").casefold()
                if media_type not in ("tv", "tv series", "series", "unknown"):
                    continue
                if any(match_key(title) in accepted for title in _search_titles(item)):
                    ids.add(aid)
        cache[cache_key] = next(iter(ids)) if len(ids) == 1 else None
    return cache[cache_key]


def source_proof(reference, group, row, expected_aid):
    """Re-evaluate sibling identity using the absolute source episode."""
    source_ep = row.get("source_episode") or row.get("episode")
    proposed = {**row, "episode": source_ep, "source_episode": source_ep,
                "episode_type": "Episode"}
    proof = sibling_work_evidence(reference, group, proposed)
    return bool(proof and proof[0] == expected_aid and proof[1] >= 2)


def promote_verified_second_season(api, plan, eligible, *, reference=None,
                                   episode_counts=None, sequel_ids=None, diagnostics=None):
    reference = sibling_index(api) if reference is None else reference
    episode_counts = {} if episode_counts is None else episode_counts
    sequel_ids = {} if sequel_ids is None else sequel_ids
    diagnostics = {} if diagnostics is None else diagnostics
    promoted = 0

    def count(name, amount=1):
        diagnostics[name] = diagnostics.get(name, 0) + amount
    for group in plan.get("groups", []):
        folder = group.get("folder") or ""
        if (group.get("mixed_season_source") or folder.startswith("__")
                or season_hint(clean_release_title(folder)) is not None
                or type_hint(folder)):
            continue
        base = clean_release_title(folder)
        # Require an actual >=3-episode contiguous continuation; an isolated
        # E13 after a 12-episode show is much more likely an OVA.
        rows = group.get("files") or []
        per_aid = {}
        for row in rows:
            if int(row.get("file_id") or 0) not in eligible:
                continue
            source = row.get("source_episode") or row.get("episode")
            if not isinstance(source, int) or source < 7:
                continue
            if classify_episode(str(row.get("path") or ""), group=folder).category != "Episode":
                continue
            count("eligible_high_numbered_episodes")
            rel = PurePosixPath(str(row.get("path") or ""))
            evidence = reference.get(rel.parent.as_posix())
            if not evidence or len(evidence["work_ids"]) != 1:
                continue
            aid = next(iter(evidence["work_ids"]))
            # Independent recognized siblings and verified episode lengths
            # outweigh an earlier automatic title guess. Explicit overrides
            # remain authoritative and are never replaced.
            if (row.get("target_anidb_id") and int(row["target_anidb_id"]) != aid
                    and row.get("mode") not in ("review", "episode_review",
                                                "auto_evidence", "strong_context",
                                                "exact_work_title", "sibling_consensus")):
                continue
            if not source_proof(reference, group, row, aid):
                continue
            count("sibling_proven_high_numbered_episodes")
            size = normal_episode_count(api, aid, episode_counts)
            if size is None or not (size < source <= size * 2):
                continue
            count("verified_s1_overflow_episodes")
            per_aid.setdefault((aid, size), []).append(row)
        for (first_aid, size), candidates in per_aid.items():
            numbers = {int(r.get("source_episode") or r["episode"]) for r in candidates}
            if (len(numbers) < 3 or min(numbers) != size + 1
                    or max(numbers) - min(numbers) + 1 != len(numbers)):
                continue
            count("contiguous_continuation_blocks")
            sequel = second_season_id(api, base, first_aid, sequel_ids)
            if sequel is None:
                count("blocks_without_exact_s2_identity")
                continue
            count("blocks_with_exact_s2_identity")
            for row in candidates:
                src = int(row.get("source_episode") or row["episode"])
                row["source_episode"] = src
                row["target_anidb_id"] = sequel
                row["episode"] = src - size
                row["episode_type"] = "Episode"
                row["mode"] = "verified_second_season"
                row["split_first_anidb_id"] = first_aid
                row["split_first_episode_count"] = size
                row["reason"] = "Shoko-verified full S1 length and exact AniDB 2nd Season identity"
                promoted += 1
    return promoted


def verify_split_row(api, group, row, *, reference=None,
                     episode_counts=None, sequel_ids=None):
    if row.get("mode") != "verified_second_season":
        return False
    reference = sibling_index(api) if reference is None else reference
    episode_counts = {} if episode_counts is None else episode_counts
    sequel_ids = {} if sequel_ids is None else sequel_ids
    first = row.get("split_first_anidb_id")
    offset = row.get("split_first_episode_count")
    src = row.get("source_episode")
    ep = row.get("episode")
    aid = row.get("target_anidb_id")
    if not all(isinstance(x, int) for x in (first, offset, src, ep, aid)):
        return False
    if offset < 6 or src != ep + offset or ep <= 0 or ep > offset:
        return False
    folder = group.get("folder") or ""
    if season_hint(clean_release_title(folder)) is not None or type_hint(folder):
        return False
    if not source_proof(reference, group, row, first):
        return False
    if normal_episode_count(api, first, episode_counts) != offset:
        return False
    return second_season_id(api, clean_release_title(folder), first, sequel_ids) == aid
