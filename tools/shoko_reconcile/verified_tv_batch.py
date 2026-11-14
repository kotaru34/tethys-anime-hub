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
    """Promote only complete TV batches; report title rejects without API calls."""
    from collections import Counter

    diagnostics = {} if diagnostics is None else diagnostics
    cache = {}
    promoted = 0
    title_gates = Counter()
    # Report large groups first. This identifies precisely why a 26-file
    # title did not even reach the expensive per-series episode API check.
    groups = plan.get("groups") or []
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
