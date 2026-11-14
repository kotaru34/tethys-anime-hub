"""Evidence-driven recovery for incomplete Shoko/AniDB title searches.

Use independent title signals (release folder, candidate titles, known public aliases),
season/part/format and episode metadata.  This module never touches Shoko or media.
Public IDs in known_aliases.json are crosswalk records, NOT made-up AniDB file IDs.
"""
from __future__ import annotations

from collections import Counter
import json
from pathlib import Path, PurePosixPath
import re

from matching import (clean_release_title, match_key, season_hint,
                      classify_episode, type_hint, similarity, target_season_supported,
                      parenthetical_title_variants, group_season_evidence)

_SEQUEL = re.compile(r"(?i)(?<!\w)(?:season\s*0*[2-9]\d?|s0*[2-9]\d?|[2-9]\d?(?:nd|rd|th)\s+season|(?:ii|iii|iv|v|vi))\b")
_PART = re.compile(r"(?i)\bpart[\s_.-]*0*([1-9]\d?)\b")
_NONALNUM_SUFFIX = re.compile(r"[∽∬∫☆★~*]", flags=re.UNICODE)


def _release_title(folder: str) -> str:
    # Extract the real title; TV-1 is a broadcast descriptor, not part of the name.
    result = clean_release_title(folder)
    result = re.sub(r"(?i)\s+(?:TV[- ]?1|202[0-9])\s*$", "", result)
    result = re.sub(r"(?i)\s+(?:TV[- ]?1|202[0-9])\s*$", "", result)
    return result.strip()


def _key(s: str) -> str:
    return match_key(s, strict=True).strip()


def _semantic_symbol(s: str) -> str:
    return "".join(_NONALNUM_SUFFIX.findall(s))


def _part(s: str) -> int | None:
    m = _PART.search(s)
    return int(m.group(1)) if m else None


def _title_candidate_confidence(group: dict, candidate: dict) -> float:
    """Comparable evidence score, not a statistical probability."""
    folder = group["folder"]
    query = _release_title(folder)
    title = str(candidate.get("title") or "")
    aliases = [title, str(candidate.get("matched_alias") or "")]
    original = group.get("queries") or []
    aliases.extend(str(x) for x in candidate.get("aliases", []))
    if not title:
        return -999
    cpart = _part(title)
    gpart = _part(folder)
    # Part 2 must never resolve to the first half of Season 2.
    if gpart and cpart and gpart != cpart:
        return -999
    if gpart and not cpart:
        return -999 if "part" in title.lower() else -0.4
    qs = season_hint(query)
    cs = season_hint(title)
    if qs is not None and cs is not None and qs != cs:
        return -999
    # Use only the canonical title for sequel identity. Cross-provider aliases
    # can repeat the franchise root for *every* season.
    if qs is not None and cs is None and qs >= 2:
        return min(0.62, similarity(query, title))
    fmt = str(candidate.get("type") or "").lower()
    gf = type_hint(folder)
    if gf == "Movie" and fmt not in ("movie", "unknown", "film"):
        return -999
    if gf == "OVA" and fmt not in ("ova", "special", "ona", "unknown"):
        return -999
    if gf is None and fmt in ("movie", "special", "ova"):
        return 0.05  # do not choose a movie or special for a plain TV folder
    # Do not erase distinctive quintuplets symbols (∽, ∬, *).
    left, right = _semantic_symbol(query), _semantic_symbol(title)
    if left != right and (left or right):
        return 0.12
    if _key(query) == _key(title):
        return 1.3
    # Strong evidence from a complete title (not its shorter franchise root).
    # A release may name the same work twice, e.g. Japanese + English.
    # Compare each complete, independently extracted title against candidate
    # aliases; never treat codec/season parentheticals as a work title.
    source_titles = [query] + parenthetical_title_variants(folder)
    best = max(similarity(source_title, x)
               for source_title in source_titles for x in aliases if x)
    if qs is not None and cs == qs:
        best += 0.14
    if gpart is not None and cpart == gpart:
        best += 0.20
    if candidate.get("episodes") is not None:
        normal = [x for x in group.get("files", []) if x.get("episode_type") == "Episode"]
        if normal and len(normal) == int(candidate["episodes"]):
            best += 0.03
    return best


def known_aliases(path: str | Path | None = None):
    loc = Path(path) if path else Path(__file__).with_name("known_aliases.json")
    if not loc.is_file():
        return []
    with loc.open(encoding="utf8") as stream:
        rows = json.load(stream)
    if not isinstance(rows, list):
        raise ValueError("Alias records must be a JSON list")
    return rows


def _choose_public_crosswalk(group: dict, records: list[dict]):
    """Require exact public work alias, including explicit episode season if nested.

    A season-neutral parent directory cannot supply an S2 identity on its
    own. If *all* unknown files have explicit consistent S02E markers, add
    one season-qualified query to permit a curated Season 2 crosswalk.
    Never use fuzzy/partial alias containment for automatic linking.
    """
    folder = _release_title(group["folder"])
    keys = {_key(folder)}
    if season_hint(folder) is None:
        season, conflict = group_season_evidence(group["folder"], group.get("files") or [])
        if not conflict and season is not None and season >= 2:
            keys.add(_key(f"{folder} Season {season}"))
    matches = []
    for entry in records:
        if any(_key(alias) in keys for alias in entry.get("aliases", []) if alias):
            matches.append(entry)
    return matches[0] if len(matches) == 1 else None


def _episode_issues(g: dict, record: dict | None):
    """Fix numbering semantics after selecting the work, without fabricating an episode."""
    folder = g["folder"]
    rows = g.get("files", [])
    for r in rows:
        path = r["path"]
        info = classify_episode(path, group=folder)
        # For titles ending with '01 - OVA', the number belongs to the special.
        if r.get("episode_type") == "Special" and not r.get("episode"):
            m = re.search(r"(?i)(?<!\d)0*([1-9]\d?)\s*[-_. ]+\s*(?:ova|oad|special)(?:[ ._()-]|$)",
                          PurePosixPath(path).stem)
            if m:
                r["episode"] = int(m.group(1))
        # An unnumbered, single movie file can be confidently E01 when the
        # selected record itself is Movie and there is no featurette path.
        if (r.get("episode_type") == "Unknown" and not r.get("episode")
                and record and str(record.get("type", "")).lower() == "movie"
                and sum(r.get("mode") != "extra" for r in rows) == 1 and not any(t in path.casefold() for t in ("/extra/", "/bonus/", "/trailer/"))):
            r["episode_type"] = "Movie"
            r["episode"] = 1
        # Movie descriptor does not always occur in title, e.g. Memory Snow.
        if (r.get("episode_type") == "Movie" and not r.get("episode")):
            r["episode"] = 1
        # A verified *single-episode* standalone OVA/ONA can use E01 even
        # without a number in its release filename. Never infer this from
        # title similarity alone or from a multi-file release.
        if (r.get("episode_type") == "Unknown" and not r.get("episode")
                and record and str(record.get("type") or "").casefold() in ("ova", "ona")
                and record.get("episodes") is not None
                and int(record["episodes"]) == 1
                and len(rows) == 1 and r.get("target_anidb_id")
                and g.get("mode") == "public_crosswalk"
                and not any(t in path.casefold() for t in ("/extra/", "/bonus/", "/trailer/"))):
            r["episode_type"] = "Episode"
            r["episode"] = 1
            r["mode"] = "public_crosswalk"
            r["reason"] = "curated exact standalone OVA/ONA identity with one metadata episode"
        # A filename like S02E14 in (Season 2 Part 2) is an *absolute*
        # episode; AniDB part 2 contains 1..12.
    if _part(folder) == 2 and record and str(record.get("type", "")).lower() in ("tv", "ona", "unknown"):
        ordinary = [r for r in rows if r.get("episode_type") == "Episode" and isinstance(r.get("episode"), int)]
        if not ordinary:
            return
        numbers = sorted({r["episode"] for r in ordinary})
        count = record.get("episodes")
        if count is not None:
            count = int(count)
        if count and len(numbers) == count and numbers == list(range(numbers[0], numbers[0] + count)) and numbers[0] > 1:
            offset = numbers[0] - 1
            for r in ordinary:
                r["source_episode"] = r.get("source_episode") or r["episode"]
                r["episode"] -= offset
                r["reason"] = f"verified contiguous Part-2 episode block; absolute-to-local offset {offset}"
        # Partial blocks must *not* have arbitrary guessed offsets.


def refine(plan: dict, records: list[dict] | None = None, catalog=None):
    if plan.get("version") != 2:
        raise ValueError("Expected plan version 2")
    records = known_aliases() if records is None else records
    from shoko_reconcile import metrics
    revisions = []
    verified_releases = {
        entry["folder"]: entry for entry in json.loads(
            Path(__file__).with_name("known_release_overrides.json").read_text(encoding="utf8")
        )
    }
    for g in plan.get("groups", []):
        rows = g.get("files", [])
        if not rows:
            continue
        initial = sum(bool(r.get("target_anidb_id") and r.get("episode") and r.get("mode") not in ("review", "extra", "episode_review")) for r in rows)
        if g.get("mode") in ("approved_override", "approved_file_override"):
            continue
        # A mixed-season folder may contain untagged files. Without source
        # season evidence they must not inherit the first-season title match.
        if g.get("mixed_season_source") and g.get("season_bucket") is None:
            continue
        # Exact release-specific correction, supported by the publisher page.
        # No franchise-wide veto: these would reduce recall for valid OVA releases.
        verified = verified_releases.get(g["folder"])
        if verified is not None:
            source_numbers = [r.get("source_episode") or r.get("episode") for r in rows]
            required = verified["episodes"]
            target_kind = verified.get("episode_type", "Episode")
            same_release = all(
                PurePosixPath(r.get("path") or "").parts[:1] == (g["folder"],)
                and r.get("episode_type") in ("Episode", target_kind)
                and r.get("mode") != "extra"
                for r in rows
            )
            # A newly downloaded one-episode subset can be linked without
            # waiting for the entire release, but never with duplicate numbers.
            unique_valid_numbers = (all(isinstance(n, int) and n in required for n in source_numbers)
                                    and len(set(source_numbers)) == len(source_numbers))
            if unique_valid_numbers and same_release:
                aid = verified["anidb_id"]
                for r in rows:
                    r["target_anidb_id"] = aid
                    r["episode"] = r.get("source_episode") or r["episode"]
                    r["episode_type"] = target_kind
                    r["mode"] = "approved_release"
                    r["reason"] = "verified publisher release identity and AniDB episode type: " + verified["source"]
                g["selected_anidb_id"] = aid
                g["mode"] = "approved_release"
                g["reason"] = "exact release folder crosswalk; not fuzzy title matching"
                continue
        crosswalk = _choose_public_crosswalk(g, records)
        ranked = sorted(((round(_title_candidate_confidence(g, c), 5), c) for c in g.get("candidates", [])), key=lambda p: -p[0])
        top_score, best = ranked[0] if ranked else (-999, None)
        second_score = ranked[1][0] if len(ranked) > 1 else -999
        selected_record = None
        reason = None
        if crosswalk:
            ident = int(crosswalk["anidb_id"])
            selected_record = next((c for c in g.get("candidates", []) if int(c["anidb_id"]) == ident), None)
            if selected_record is None:
                selected_record = {"anidb_id": ident, "title": crosswalk["title"],
                                   "type": crosswalk.get("type", "Unknown"),
                                   "episodes": crosswalk.get("episodes"),
                                   "season": crosswalk.get("season"),
                                   "source": "curated_crosswalk"}
            else:
                # Inject trusted media type and series episode count if absent.
                selected_record = dict(selected_record)
                if selected_record.get("type") in ("Unknown", None):
                    selected_record["type"] = crosswalk.get("type") or "Unknown"
                if not selected_record.get("episodes"):
                    selected_record["episodes"] = crosswalk.get("episodes")
                if selected_record.get("season") is None and crosswalk.get("season") is not None:
                    selected_record["season"] = crosswalk["season"]
            # The later per-file season safety guard consumes the ranked
            # group candidate, not just the temporary selected record.
            for candidate in g.get("candidates", []):
                if (int(candidate.get("anidb_id") or -1) == ident
                        and candidate.get("season") is None
                        and crosswalk.get("season") is not None):
                    candidate["season"] = crosswalk["season"]
            reason = "exact localized/public-series alias crosswalk"
        elif best and top_score >= 0.91 and top_score - second_score >= 0.075:
            selected_record = best
            reason = "unambiguous full-title + season/part/media-type evidence"
        if selected_record:
            aid = int(selected_record["anidb_id"])
            for r in rows:
                if r.get("mode") in ("review", "episode_review") and r.get("episode_type") not in ("Extra",):
                    # Keep separately named media (including chibi spin-offs) separate.
                    if "youjo shenki" in r["path"].casefold() and "youjo senki" in g["folder"].casefold():
                        continue
                    r["target_anidb_id"] = aid
                    # Identifying a work does not establish its episode.
                    # Preserve a visible review state for unnumbered files,
                    # even when the title match is otherwise unambiguous.
                    if not isinstance(r.get("episode"), int) or r["episode"] <= 0:
                        r["mode"] = "episode_review"
                        r["reason"] = "series identified, but episode identity is unverified"
                        continue
                    r["mode"] = "public_crosswalk" if crosswalk else "strong_context"
                    r["reason"] = reason
            if g.get("mode") == "review":
                g["selected_anidb_id"] = aid
                g["mode"] = "public_crosswalk" if crosswalk else "strong_context"
                g["reason"] = reason
            if not any(int(c.get("anidb_id") or -1) == aid for c in g.get("candidates", [])):
                g.setdefault("candidates", []).insert(0, dict(selected_record, score=1.0, matched_alias=g["title_guess"]))
        # Preserve prior selections; can still classify movie/OVA from Shoko
        # even if no new selection was made.
        if not selected_record and g.get("selected_anidb_id"):
            aid = int(g["selected_anidb_id"])
            selected_record = next((c for c in g.get("candidates", []) if int(c.get("anidb_id") or -1) == aid), None)
        _episode_issues(g, selected_record)
        # An AniDB *work* of type OVA/ONA/SPECIAL has ordinary E01..En episodes;
        # S01 refers to a *special episode attached to a different work*.
        # Shoko 5.3.3 uses that distinction in LinkFromSeries.
        if selected_record and str(selected_record.get("type") or "").lower() in ("ova", "ona", "special"):
            for r in rows:
                if r.get("episode_type") == "Special" and isinstance(r.get("episode"), int) and r["episode"] > 0:
                    r["episode_type"] = "Episode"
                    r["reason"] = (r.get("reason") or "") + "; standalone OVA/ONA work uses E-numbering"
        # AniDB may split a full 24-episode S02 release into two 12-episode
        # works. Recover the offset using the explicit '2nd Season Part 2'
        # candidate and its verified count, not an arbitrary +/-12 guess.
        if (season_hint(g["folder"]) == 2 and not _part(g["folder"]) and selected_record
                and selected_record.get("episodes") and int(selected_record["episodes"]) > 1):
            first_count = int(selected_record["episodes"])
            high = [r for r in rows if r.get("episode_type") == "Episode"
                    and isinstance(r.get("episode"), int) and r["episode"] > first_count]
            if high:
                names = [c for c in g.get("candidates", [])
                         if _part(str(c.get("title") or "")) == 2
                         and str(c.get("type") or "").casefold() in ("tv", "ona", "unknown")]
                names.sort(key=lambda c: similarity(_release_title(g["folder"]),
                                                    str(c.get("title") or "")), reverse=True)
                sequel = names[0] if names else None
                if sequel and sequel.get("episodes") and int(sequel["episodes"]) >= max(r["episode"] - first_count for r in high):
                    for r in high:
                        r["source_episode"] = r.get("source_episode") or r["episode"]
                        r["episode"] -= first_count
                        r["target_anidb_id"] = int(sequel["anidb_id"])
                        r["reason"] = f"season split: Part 2 episode {r['episode']} after {first_count}-episode Part 1"
                else:
                    for r in high:
                        r["target_anidb_id"] = None
                        r["mode"] = "episode_review"
                        r["reason"] = "exceeds Part 1 episode count; Part 2 is not identified"
        # Resolve *nested* secondary works using exact-title catalog evidence,
        # never assign their filenames to the containing main anime.
        if catalog is not None:
            for r in rows:
                path_parts = PurePosixPath(r["path"]).parts
                if len(path_parts) < 3 or r.get("mode") == "extra":
                    continue
                subdir = path_parts[1]
                if not re.search(r"[^0-9\\W]", subdir, re.UNICODE):
                    continue
                if _key(subdir) in (_key(_release_title(g["folder"])), "special", "specials", "ova", "extras", "extra"):
                    continue
                valid = [c for c in catalog.lookup(subdir) if any(
                    _key(a) == _key(subdir) for a in [c.get("title", "")] + list(c.get("aliases", [])))]
                if len({int(c["anidb_id"]) for c in valid}) == 1 and r.get("episode") and r.get("episode_type") != "Extra":
                    c = valid[0]
                    r["target_anidb_id"] = int(c["anidb_id"])
                    r["mode"] = "nested_exact_work"
                    r["episode_type"] = "Episode" if str(c.get("type") or "").lower() in ("ona", "ova", "special") else r["episode_type"]
                    r["reason"] = "independent nested work identified by exact external title and AniDB crosswalk"
        for r in rows:
            if r.get("episode") and r.get("target_anidb_id") and r.get("mode") == "episode_review":
                r["mode"] = "strong_context"  # newly validated episode inference, same series as before
            if r.get("episode") and r.get("target_anidb_id") and r.get("mode") == "review" and selected_record and g.get("mode") != "review":
                r["mode"] = "public_crosswalk" if crosswalk else "strong_context"
            # No AniDB series can have a normal E25 when it is a 24-ep TV:
            # keep such files for manual/episode title checks, not false successes.
            if (r.get("episode_type") == "Episode" and r.get("episode") and selected_record and selected_record.get("episodes")
                    and r["episode"] > int(selected_record["episodes"]) and not _part(g["folder"])):
                r["target_anidb_id"] = None
                r["mode"] = "episode_review"
                r["reason"] = "episode number exceeds verified series length; potentially a recap or special"
        # Defense in depth: old v2 plans and refinement promotions bypass the
        # fresh-search ranking stage. Never let one promote an S02 file to S01.
        for r in rows:
            if r.get("target_anidb_id") and not target_season_supported(g, r):
                r["target_anidb_id"] = None
                r["mode"] = "episode_review"
                r["reason"] = "candidate season is not supported by source season evidence"
        final = sum(bool(r.get("target_anidb_id") and r.get("episode") and r.get("mode") not in ("review", "extra", "episode_review")) for r in rows)
        if final > initial:
            revisions.append({"folder": g["folder"], "additional_potential": final - initial, "series":g.get("selected_anidb_id")})
    plan["metrics"] = metrics(plan)
    plan["refinements"] = {"version": "2.2", "rescued_groups": revisions,
                           "crosswalk_count": len(records),
                           "no_remote_validation": True}
    return plan
