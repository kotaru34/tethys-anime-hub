#!/usr/bin/env python3
"""Conservative, opt-in automatic fallback for Shoko 5.3.3.

Runs after Shoko's own hash/AniDB processing, not instead of it. Never writes
to /Anime, never applies a historical plan and never fabricates AniDB File IDs.
Ambiguous matches remain Unrecognized for manual review.
"""
from __future__ import annotations

import argparse
import json
import os
import re
from pathlib import Path, PurePosixPath
import sys

from catalog import AliasCatalog
from matching import target_season_supported
from shoko_reconcile import ShokoAPI, _write_private_json, apply, prepare


def eligible_final_files(files, *, media_root):
    """Select Shoko-unknown final media files without any age/stability polling.

    qBittorrent is the source of truth for download completion. Its .!qB/.qb!
    partial files are excluded. Remaining checks only prevent stale/missing,
    empty, or path-escaping media paths from entering a link plan.
    """
    root = Path(media_root).resolve()
    eligible = set()
    for record in files:
        locs = record.get("Locations") or []
        if not locs:
            continue
        rel = str(locs[0].get("RelativePath") or "")
        pure = PurePosixPath(rel)
        if (not rel or rel.casefold().endswith((".!qb", ".qb!"))
                or pure.is_absolute() or ".." in pure.parts):
            continue
        try:
            full = (root / rel).resolve(strict=True)
            if not full.is_relative_to(root) or not full.is_file():
                continue
            if full.stat().st_size <= 0:
                continue
        except (OSError, RuntimeError):
            continue
        eligible.add(int(record["ID"]))
    return eligible


def special_identity_rejection_reason(group, row):
    """Reject a TV/OVA type mismatch even when old plans claim a strong title.

    A release's absolute "- 13 (OVA 1)" is *not* proof of TV E13 or S13.
    The only automatic OVA E-number link is to a separately identified
    OVA/ONA work, not an arbitrary special attached to a TV work.
    """
    if row.get("mode") in {"approved_release", "approved_file_override", "approved_override"}:
        return None
    from matching import classify_episode
    path = str(row.get("path") or "")
    info = classify_episode(path, group=group.get("folder") or "")
    stem = PurePosixPath(path).stem
    explicit_ova = re.search(
        r"(?i)(?:^|[\\s._(\\[\\-])(?:ova|oad|ona)(?:$|[\\s._)\\]\\-])", stem)
    if info.category != "Special":
        if explicit_ova:
            return "ova_filename_not_classified_as_special"
        return None
    if (isinstance(info.number, int) and info.number > 0
            and info.number != row.get("episode")):
        return "special_filename_episode_number_mismatch"
    if row.get("episode_type") == "Episode":
        target = next((c for c in group.get("candidates") or []
                       if c.get("anidb_id") == row.get("target_anidb_id")), None)
        if not target or str(target.get("type") or "").casefold() not in {"ova", "ona"}:
            return "standalone_special_work_identity_unverified"
    if explicit_ova and row.get("episode_type") != "Episode":
        return "standalone_ova_requires_separate_work"
    return None


def auto_link_rejection_reason(group, row):
    """Return the specific failed safety gate, or None for an approved row.

    Do not confuse the plan's 'mode'/'reason' (title inference) with the
    independent gates for automatic linking. This is the one source of truth
    for both the write policy and the operator's read-only diagnostics.
    """
    mode = row.get("mode")
    # A local sibling consensus is anchored by Shoko's *existing* exact-work
    # XRefs and same-season, same-directory episode files, not fuzzy titles.
    if mode == "sibling_consensus":
        if (row.get("episode_type") != "Episode"
                or int(row.get("sibling_evidence_count") or 0) < 2):
            return "insufficient_sibling_episode_evidence"
    elif mode == "verified_second_season":
        # The actual first-work episode count and exact AniDB sequel title
        # are re-verified at apply(), not inferred from a fuzzy S2 score.
        offset = row.get("split_first_episode_count")
        first = row.get("split_first_anidb_id")
        source = row.get("source_episode")
        target = row.get("episode")
        if not all(isinstance(x, int) for x in (offset, first, source, target)):
            return "sequel_split_evidence_missing"
        if offset < 6 or target < 1 or target > offset or source != offset + target:
            return "sequel_split_evidence_mismatch"
    elif not target_season_supported(group, row):
        return "candidate_season_unsupported"
    if mode not in {"approved_release", "public_crosswalk", "prior_exact_title",
                    "nested_exact_work", "exact_work_title", "auto_evidence",
                    "strong_context", "sibling_consensus", "verified_second_season"}:
        return "mode_requires_manual_review"
    special_gate = special_identity_rejection_reason(group, row)
    if special_gate:
        return special_gate
    if mode == "exact_work_title":
        # Independently recompute full-title uniqueness at the write boundary.
        # Candidate scores are only fuzzy ranks; an exact title identity
        # must not be rejected for having a near-score non-exact sequel.
        from refinements import unique_exact_work_candidate
        unique = unique_exact_work_candidate(group)
        if unique is None or int(unique["anidb_id"]) != row.get("target_anidb_id"):
            return "exact_work_title_not_unique_or_changed"
    # AniDB "Other" is only auto-linked for publisher-verified overrides.
    kind = row.get("episode_type")
    allowed = ({"Episode", "Special", "Movie", "Other"} if mode == "approved_release"
               else {"Episode", "Special", "Movie"})
    if kind not in allowed:
        return "unsupported_episode_type"
    aid, ep = row.get("target_anidb_id"), row.get("episode")
    if not isinstance(aid, int) or not isinstance(ep, int) or ep <= 0:
        return "missing_work_or_episode_identity"
    src = row.get("source_episode")
    if src is not None and src != ep and mode != "verified_second_season":
        return "episode_number_shift_requires_review"
    if mode != "approved_release":
        # Fractional releases like Goblin Slayer 10.5 are interstitial
        # recaps, not AniDB special S10. Do not guess their special number.
        from matching import classify_episode
        info = classify_episode(row.get("path") or "", group=group.get("folder") or "")
        if info.fraction is not None and mode != "approved_file_override":
            return "fractional_episode_special_identity_unverified"
        if mode == "sibling_consensus" and info.category != "Episode":
            return "sibling_filename_is_not_normal_episode"
    if mode in {"auto_evidence", "strong_context"}:
        candidates = group.get("candidates") or []
        selected = [c for c in candidates if c.get("anidb_id") == aid]
        if not selected:
            return "selected_candidate_not_in_ranked_results"
        score = float(selected[0].get("score") or 0)
        if score < 0.98:
            return "selected_candidate_score_below_0.98"
        if any(float(c.get("score") or 0) >= score - 0.18
               for c in candidates if c.get("anidb_id") != aid):
            return "competing_candidate_within_0.18"
    return None


def is_safe_automatic_link(group, row):
    """Approve only if every evidence, season, episode, and margin gate passes."""
    return auto_link_rejection_reason(group, row) is None


def keep_safe_rows(plan, eligible):
    """Make a new private plan containing only eligible safe rows."""
    groups = []
    reviewed = 0
    for group in plan["groups"]:
        safe = []
        for row in group.get("files", []):
            if int(row["file_id"]) not in eligible:
                continue
            if is_safe_automatic_link(group, row):
                safe.append(row)
            else:
                reviewed += 1
        if safe:
            groups.append({**group, "files": safe, "count": len(safe)})
    return {**plan, "groups": groups}, reviewed


def review_diagnostics(plan, eligible, *, max_groups=12):
    """Explain why *actual automatic-link gates* rejected rows, not title prose."""
    from collections import Counter
    by_mode = Counter()
    by_gate = Counter()
    by_group = Counter()
    by_original_reason = Counter()
    examples = {}
    for group in plan.get("groups", []):
        for row in group.get("files", []):
            if int(row["file_id"]) not in eligible:
                continue
            gate = auto_link_rejection_reason(group, row)
            if gate is None:
                continue
            by_gate[gate] += 1
            by_mode[str(row.get("mode") or "unclassified")] += 1
            by_original_reason[str(row.get("reason") or group.get("reason") or "unclassified")] += 1
            folder = str(group.get("folder") or "unknown")
            by_group[folder] += 1
            examples.setdefault(folder, {"folder": folder, "group_mode": group.get("mode"),
                                         "group_reason": group.get("reason")})
    top = []
    for folder, count in by_group.most_common(max_groups):
        top.append({**examples[folder], "files": count})
    return {
        "review_by_mode": dict(sorted(by_mode.items())),
        "review_by_gate": dict(by_gate.most_common()),
        "review_by_reason": dict(by_original_reason.most_common(8)),
        "review_top_groups": top,
        "review_groups_total": len(by_group),
    }


def run(api, *, state_path=None, plan_path, media_root="/Anime", catalog=None,
        minimum_age=None, now=None, do_apply=False, refresh_requests=None):
    # state_path, minimum_age, and now are retained only for compatibility
    # with earlier callers. No age checks, state-file I/O or maturity timers.
    root = Path(media_root)
    if not root.is_dir() or not os.path.ismount(root):
        raise RuntimeError(f"Refusing to reconcile: {root} is not a mounted media directory")
    unknown = api.unrecognized()
    eligible = eligible_final_files(unknown, media_root=root)
    summary = {"currently_unrecognized": len(unknown),
               "eligible_final_files": len(eligible),
               "approved_for_auto": 0,
               "needs_review": 0, "submitted": 0}
    if not eligible:
        return summary
    # Do NOT wait for Shoko's global queue to become empty. It includes
    # non-blocking image/creator/character fetches which may take hours.
    # Final-file eligibility is enforced by eligible_final_files() above, while
    # apply() rechecks the currently-unrecognized file, original path,
    # local AniDB series identity, and actual destination episode.
    # If series/episodes are not ready yet, apply() queues only that series
    # metadata refresh and returns awaiting_series_refresh.
    plan = prepare(api, overrides={}, catalog=catalog, aggressive=False)
    # For a long-running RSS release, already recognized E01/E02 in the same
    # exact directory are stronger independent work evidence than a fuzzy
    # title match. Importing XRefs is read-only; never weaken safety checks.
    sibling_reference = None
    try:
        from local_siblings import sibling_index, promote_linked_siblings
        sibling_reference = sibling_index(api)
        summary["sibling_consensus_promoted"] = promote_linked_siblings(
            api, plan, eligible, reference=sibling_reference)
    except Exception as exc:
        # A missing/unsupported XRefs list should never prevent the existing
        # safe-title policy from doing its work.
        summary["sibling_evidence_error"] = f"{type(exc).__name__}: {exc}"
    # Convert absolute episode numbering (e.g. E14..E26 in a 13+13 TV
    # release) only with verified Shoko S1 episode count, two matching
    # sibling anchors, and an exact distinct AniDB '2nd Season' work.
    # No generic subtraction based on filename alone.
    try:
        from season_continuations import promote_verified_second_season
        summary["verified_second_season_promoted"] = promote_verified_second_season(
            api, plan, eligible, reference=sibling_reference)
    except Exception as exc:
        summary["sequel_evidence_error"] = f"{type(exc).__name__}: {exc}"
    # Any remaining sibling E13+ whose episode does not exist in its
    # original work must remain review; applying it would only defer forever.
    try:
        from local_siblings import demote_nonexistent_sibling_episodes
        summary["out_of_range_siblings_demoted"] = demote_nonexistent_sibling_episodes(
            api, plan, reference=sibling_reference)
    except Exception as exc:
        summary["sibling_episode_check_error"] = f"{type(exc).__name__}: {exc}"
    # Keep a current, read-only-to-operators inspection snapshot even when
    # *nothing* qualifies for auto-link. This is the critical case when
    # unknowns exceed the configured quality target.
    inspection_path = Path(plan_path).with_suffix(".review.json")
    _write_private_json(inspection_path, plan)
    summary["review_plan"] = str(inspection_path)
    total = plan.get("source_total_files_at_scan")
    if isinstance(total, int) and total > 0:
        summary["unknown_percent"] = round(100 * len(unknown) / total, 2)
        summary["additional_links_for_5pct"] = max(0, len(unknown) - int(total * 0.05))
    safe_plan, rejected = keep_safe_rows(plan, eligible)
    summary["approved_for_auto"] = sum(len(g["files"]) for g in safe_plan["groups"])
    summary["needs_review"] = rejected
    if rejected:
        summary.update(review_diagnostics(plan, eligible))
    if summary["approved_for_auto"]:
        _write_private_json(plan_path, safe_plan)
        if do_apply:
            result = apply(api, safe_plan,
                           journal=str(Path(plan_path).with_suffix(".journal.json")),
                           refresh_requests=refresh_requests,
                           sibling_reference=sibling_reference)
            summary.update({"submitted": result["submitted"], "errors": result["errors"],
                            "awaiting_series_refresh": result["awaiting_series_refresh"],
                            "deferred": result["deferred"],
                            "deferred_by_reason": result["deferred_by_reason"],
                            "deferred_examples": result["deferred_examples"]})
    return summary


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default=os.getenv("SHOKO_URL", "http://127.0.0.1:8111"))
    parser.add_argument("--catalog")
    parser.add_argument("--media-root", default="/Anime")
    parser.add_argument("--state", default="/var/lib/shoko-reconcile/seen.json",
                        help="Legacy compatibility; ignored (no state-file I/O)")
    parser.add_argument("--plan", default="/var/lib/shoko-reconcile/auto-plan.json")
    parser.add_argument("--minimum-age", type=int, default=None, metavar="SECONDS",
                        help="Legacy compatibility; ignored (no age-based delays)")
    parser.add_argument("--apply", action="store_true", help="Submit safe links, otherwise dry-run")
    parser.add_argument("--confirm", help="Must equal LINK for --apply")
    args = parser.parse_args(argv)
    if args.apply and args.confirm != "LINK":
        parser.error("--apply requires --confirm LINK")
    key = os.getenv("SHOKO_API_KEY")
    if not key:
        parser.error("SHOKO_API_KEY is missing")
    catalog = AliasCatalog(args.catalog) if args.catalog else None
    result = run(
        ShokoAPI(args.url, key),
        state_path=args.state, plan_path=args.plan,
        media_root=args.media_root, catalog=catalog,
        minimum_age=args.minimum_age, do_apply=args.apply)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
