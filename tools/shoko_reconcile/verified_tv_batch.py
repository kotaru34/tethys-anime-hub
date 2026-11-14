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
                      season_hint, target_season_supported, type_hint, year_hint)


_ROMAN_SEASONS = {"ii": "2", "iii": "3", "iv": "4", "v": "5", "vi": "6",
                  "vii": "7", "viii": "8"}


def _compact_title(title):
    canonical = match_key(str(title or ""), strict=True)
    if not canonical or not re.fullmatch(r"[a-z0-9 ]+", canonical):
        return None
    # Change only a terminal, standalone Roman season index; no general
    # abbreviation/number substitution is permitted.
    parts = canonical.split()
    if parts and parts[-1] in _ROMAN_SEASONS:
        parts[-1] = _ROMAN_SEASONS[parts[-1]]
    # Normalize only a terminal, explicitly labeled season suffix.
    # A bare number inside a title must not become an inferred season.
    if len(parts) >= 3 and parts[-1] == "season" and parts[-2].isdigit():
        parts.pop()
    elif len(parts) >= 3 and parts[-2] == "season" and parts[-1].isdigit():
        parts.pop(-2)
    canonical = " ".join(parts)
    # Full-length romaji permits an exact comparison without whitespace.
    # Short works require full word-boundary equality; no fuzzy similarity.
    compact = canonical.replace(" ", "")
    return compact if len(compact) >= 24 and len(parts) >= 3 else canonical


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


def unique_tv_work(group, *, failure=None):
    """Require a unique full-title TV-like work, including strict S2 aliases."""
    def reject(reason):
        if failure is not None:
            failure.append(reason)
        return None

    folder = group.get("folder") or ""
    if (folder.startswith("__") or group.get("mixed_season_source")
            or type_hint(folder) is not None):
        return reject("nonstandard_or_mixed_folder")
    release = clean_release_title(folder)
    key = _compact_title(release)
    if key is None:
        return reject("not_latin_full_title")

    requested_season = season_hint(release)
    # Ordinary distributors frequently name a sequel "Goblin Slayer 2"
    # while AniDB calls it "Goblin Slayer II". A trailing 2 alone NEVER
    # selects a work: its candidate must independently prove Season 2.
    trailing = re.search(r"[\s._-]+([2-9])$", release)
    if requested_season is None and trailing:
        requested_season = int(trailing.group(1))
    base_key = (_compact_title(release[:trailing.start()])
                if trailing else None)

    found = {}
    typed_count = title_count = 0
    for candidate in group.get("candidates") or []:
        aid = candidate.get("anidb_id")
        candidate_type = str(candidate.get("type") or "").casefold()
        if (not isinstance(aid, int)
                or candidate_type not in {"tv", "tv series", "unknown", ""}):
            continue
        typed_count += 1

        # Use source-independent season evidence from the AniDB candidate,
        # not from the filename's number alone.
        candidate_season = candidate.get("season")
        if candidate_season is None:
            candidate_season = season_hint(str(candidate.get("title") or ""))
        aliases = list(_aliases(candidate))
        exact_match = any(_compact_title(alias) == key for alias in aliases)
        # When a terminal Arabic 2 is the release's season notation, the
        # official S2 title may omit it (e.g. Kaguya-sama "?"). The base
        # title is acceptable ONLY for the independently tagged S2 work.
        season_tag_match = (
            bool(trailing) and requested_season == candidate_season
            and base_key is not None
            and any(_compact_title(alias) == base_key for alias in aliases)
        )
        if not (exact_match or season_tag_match):
            continue
        title_count += 1
        if year_hint(str(candidate.get("title") or "")) and not year_hint(release):
            continue
        if requested_season is not None:
            if candidate_season != requested_season:
                continue
        elif candidate_season is not None and candidate_season > 1:
            # "High School DxD Born" may be a real unnumbered S3 title:
            # the CANONICAL work title must match exactly, never a shared
            # franchise-root alias such as "High School DxD".
            if _compact_title(candidate.get("title")) != key:
                continue
        found[aid] = candidate
    if not typed_count:
        return reject("no_tv_or_unknown_candidates")
    if not title_count:
        return reject("no_exact_full_title_alias")
    if not found:
        return reject("season_or_year_guard")
    if len(found) != 1:
        return reject("multiple_exact_tv_work_ids")
    return next(iter(found.values()))


def _batch_rows(group, eligible=None, *, failure=None):
    """Collect the numbered main episodes, not unrelated bonuses in a batch.

    This can tolerate explicitly classified specials and extras in the same
    torrent. It never uses their numbering to complete a TV season and never
    silently skips an unknown/unclassified file.
    """
    def reject(reason):
        if failure is not None:
            failure.append(reason)
        return None

    folder = group.get("folder") or ""
    rows = []
    for row in group.get("files") or []:
        rel = str(row.get("path") or "")
        path = PurePosixPath(rel)
        if not path.parts or path.parts[0] != folder:
            return reject("file_outside_release_folder")
        info = classify_episode(rel, group=folder)
        if info.category in {"Extra", "Special"}:
            # Explicitly marked non-TV works remain unlinked and never serve
            # as positive evidence for the main season.
            continue
        if len(path.parts) != 2:
            return reject("nested_unclassified_or_tv_file")
        if info.category != "Episode":
            return reject("unparseable_main_episode")
        if (not isinstance(info.number, int) or info.number <= 0
                or row.get("episode") != info.number
                or row.get("episode_type") != "Episode"
                or row.get("source_episode") not in (None, info.number)
                or row.get("mode") in {"approved_release", "approved_override",
                                       "approved_file_override", "nested_exact_work",
                                       "public_crosswalk", "prior_exact_title",
                                       "verified_second_season"}):
            return reject("episode_number_or_existing_proof_conflict")
        if eligible is not None and int(row.get("file_id") or 0) not in eligible:
            return reject("ineligible_main_episode")
        rows.append((info.number, row))
    if len(rows) < 6:
        return reject("insufficient_numbered_main_episodes")
    numbers = [number for number, _ in rows]
    if len(numbers) != len(set(numbers)):
        return reject("duplicate_main_episode_number")
    return rows


def _episodes(api, aid, cache):
    """Return the actual AniDB episode set and an explicit metadata state."""
    if aid not in cache:
        series = api.local_series(aid)
        ids = (series or {}).get("IDs") or {}
        if int(ids.get("AniDB") or -1) != aid or not ids.get("ID"):
            cache[aid] = (None, "series_not_local")
        else:
            episodes = api.available_episodes(int(ids["ID"]))
            cache[aid] = (episodes, "inventory_ready" if episodes else "episode_inventory_empty")
    return cache[aid]


def tv_batch_proof(api, group, *, eligible=None, cache=None, failure=None):
    """Prove unique exact work and full AniDB E01..EN, reporting the blocker."""
    cache = {} if cache is None else cache

    def reject(reason):
        if failure is not None:
            failure.append(reason)
        return None

    candidate = unique_tv_work(group)
    if candidate is None:
        return reject("work_identity_not_unique")
    row_failure = []
    rows = _batch_rows(group, eligible, failure=row_failure)
    if not rows:
        return reject(row_failure[0] if row_failure else "file_episode_parsing_or_layout")
    numbers = {number for number, _ in rows}
    if numbers != set(range(1, len(numbers) + 1)):
        return reject("non_contiguous_local_episode_numbers")
    aid = int(candidate["anidb_id"])
    if any(not target_season_supported(
            group, {**row, "target_anidb_id": aid, "mode": "strong_context"})
            for _, row in rows):
        return reject("candidate_season_unsupported")
    episodes, metadata_state = _episodes(api, aid, cache)
    if not episodes:
        return reject(metadata_state)
    ordinary = {n for kind, n in episodes if kind == "Episode"}
    n = len(ordinary)
    if not (6 <= n <= 26 and ordinary == set(range(1, n + 1))):
        return reject("anidb_ordinary_episodes_not_contiguous")
    # A verified season may be still airing: E01..E07 of a 12-episode
    # work is legitimate. Require an exact, unique work, a contiguous
    # beginning-of-season prefix, and real Shoko AniDB Episode XRefs for
    # every released file. Missing episodes are never invented.
    if not numbers <= ordinary:
        return reject("episode_inventory_mismatch")
    return aid, n, [row for _, row in rows]


def promote_verified_tv_batch(api, plan, eligible, *, diagnostics=None,
                              refresh_requests=None, prefetch_missing=False,
                              refresh_cooldown=900):
    """Prove TV batches; optionally request only missing target-series metadata.

    A matching title and a contiguous set of local episode numbers can
    authorize a *targeted metadata refresh*, never a link. Only a future
    recheck of the full live AniDB inventory can authorize the link itself.
    """
    from collections import Counter
    import time

    diagnostics = {} if diagnostics is None else diagnostics
    cache = {}
    promoted = 0
    title_gates = Counter()
    proof_gates = Counter()
    pending_aids = set()
    groups = plan.get("groups") or []
    eligible = {int(item) for item in eligible}
    for group in sorted(groups, key=lambda g: -len(g.get("files") or [])):
        if len(group.get("files") or []) < 6:
            continue
        reason = []
        candidate = unique_tv_work(group, failure=reason)
        if candidate is None:
            gate = reason[0] if reason else "unknown_title_gate"
            title_gates[gate] += 1
            if len(diagnostics.setdefault("title_gate_examples", [])) < 14:
                diagnostics["title_gate_examples"].append({
                    "folder": group.get("folder"),
                    "files": len(group.get("files") or []),
                    "gate": gate,
                    "candidate_titles": [
                        str(c.get("title") or "")[:110]
                        for c in (group.get("candidates") or [])[:2]],
                })
        else:
            title_gates["passed_exact_tv_title"] += 1
    diagnostics["screened_large_groups"] = sum(
        len(group.get("files") or []) >= 6 for group in groups)
    diagnostics["title_gate_reasons"] = dict(sorted(title_gates.items()))

    for group in groups:
        candidate = unique_tv_work(group)
        if candidate is None:
            continue
        diagnostics["exact_spaced_tv_groups"] = diagnostics.get("exact_spaced_tv_groups", 0) + 1
        failure = []
        proof = tv_batch_proof(api, group, eligible=eligible, cache=cache,
                               failure=failure)
        if proof is None:
            gate = failure[0] if failure else "unknown_proof_gate"
            proof_gates[gate] += 1
            diagnostics["incomplete_or_unverified_tv_groups"] = diagnostics.get(
                "incomplete_or_unverified_tv_groups", 0) + 1
            if len(diagnostics.setdefault("proof_gate_examples", [])) < 14:
                diagnostics["proof_gate_examples"].append({
                    "folder": group.get("folder"),
                    "files": len(group.get("files") or []),
                    "anidb_id": candidate["anidb_id"],
                    "gate": gate})
            if (prefetch_missing and refresh_requests is not None
                    and gate in {"series_not_local", "episode_inventory_empty"}):
                aid = int(candidate["anidb_id"])
                pending_aids.add(aid)
                now = time.monotonic()
                if (aid not in refresh_requests
                        or now - refresh_requests[aid] >= refresh_cooldown):
                    api.refresh_series(aid)
                    refresh_requests[aid] = now
                    diagnostics["target_metadata_refreshes"] = (
                        diagnostics.get("target_metadata_refreshes", 0) + 1)
            continue
        aid, count, rows = proof
        for row in rows:
            row["target_anidb_id"] = aid
            row["mode"] = "verified_tv_batch"
            row["verified_tv_episode_count"] = count
            row["reason"] = "unique full TV title, contiguous E01..EK release and verified AniDB E01..EN inventory"
            promoted += 1
        diagnostics["verified_tv_groups"] = diagnostics.get("verified_tv_groups", 0) + 1
    diagnostics["proof_gate_reasons"] = dict(sorted(proof_gates.items()))
    diagnostics["pending_tv_metadata_aids"] = sorted(pending_aids)
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
