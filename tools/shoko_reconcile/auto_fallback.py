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
from pathlib import Path, PurePosixPath
import sys
import time

from catalog import AliasCatalog
from matching import target_season_supported
from shoko_reconcile import ShokoAPI, _write_private_json, apply, prepare


def stable_unknowns(files, old_state, *, now, media_root, minimum_age=900):
    """Return IDs still unknown with unchanged filesystem identity over time."""
    root = Path(media_root).resolve()
    current = {}
    eligible = set()
    for record in files:
        fid = int(record["ID"])
        locs = record.get("Locations") or []
        if not locs:
            continue
        rel = str(locs[0].get("RelativePath") or "")
        pure = PurePosixPath(rel)
        if not rel or pure.is_absolute() or ".." in pure.parts:
            continue
        try:
            full = (root / rel).resolve(strict=True)
            if not full.is_relative_to(root) or not full.is_file():
                continue
            st = full.stat()
        except (OSError, RuntimeError):
            continue
        if st.st_size <= 0:
            continue
        previous = old_state.get(str(fid), {})
        fingerprint = {"path": rel, "size": st.st_size, "mtime_ns": st.st_mtime_ns}
        same = all(previous.get(k) == v for k, v in fingerprint.items())
        first_seen = float(previous.get("first_seen", now)) if same else now
        current[str(fid)] = {**fingerprint, "first_seen": first_seen}
        if same and now - first_seen >= minimum_age and now - st.st_mtime >= minimum_age:
            eligible.add(fid)
    return current, eligible


def is_safe_automatic_link(group, row):
    """Approve only well-evidenced work identity; episode checked again by apply()."""
    if not target_season_supported(group, row):
        return False
    mode = row.get("mode")
    if mode not in {"approved_release", "public_crosswalk", "prior_exact_title",
                    "nested_exact_work", "auto_evidence", "strong_context"}:
        return False
    # AniDB "Other" is *not* normally safe for auto matching. Allow O01/O02
    # only for an explicit publisher-verified release override.
    kind = row.get("episode_type")
    if kind not in ({"Episode", "Special", "Movie", "Other"} if mode == "approved_release"
                    else {"Episode", "Special", "Movie"}):
        return False
    aid, ep = row.get("target_anidb_id"), row.get("episode")
    if not isinstance(aid, int) or not isinstance(ep, int) or ep <= 0:
        return False
    # No automatic interpretation of shifted/recap episode numbers.
    src = row.get("source_episode")
    if src is not None and src != ep:
        return False
    # Only explicitly verified release-specific overrides bypass fuzzy matching.
    # Legacy group-level vetoes for all OVAs were removed: they cost 9/981
    # viable files in the original archive, including correctly identified OVA.
    # "strong_context" is an independently refined *title* choice, but its
    # initial 0.91 / 0.075 margins are NOT safe enough for unattended use.
    # Require exactly the same strict independent score and separation as
    # "auto_evidence". Candidate scores are ranking evidence, not calibrated
    # probabilities of a correct match.
    if mode in {"auto_evidence", "strong_context"}:
        candidates = group.get("candidates") or []
        selected = [c for c in candidates if c.get("anidb_id") == aid]
        if not selected:
            return False
        chosen = selected[0]
        score = float(chosen.get("score") or 0)
        if score < 0.98:
            return False
        if any(float(c.get("score") or 0) >= score - 0.18
               for c in candidates if c.get("anidb_id") != aid):
            return False
    return True


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
    """Explain conservative rejections, without adding speculative links.

    Group names and file paths stay in a private plan on the Shoko host;
    the journal contains only counts and at most 12 release folder names.
    """
    from collections import Counter
    by_mode = Counter()
    by_reason = Counter()
    by_group = Counter()
    examples = {}
    for group in plan.get("groups", []):
        for row in group.get("files", []):
            if int(row["file_id"]) not in eligible or is_safe_automatic_link(group, row):
                continue
            mode = str(row.get("mode") or "unclassified")
            by_mode[mode] += 1
            reason = str(row.get("reason") or group.get("reason") or "unclassified")
            by_reason[reason] += 1
            folder = str(group.get("folder") or "unknown")
            by_group[folder] += 1
            examples.setdefault(folder, {"folder": folder, "group_mode": group.get("mode"),
                                         "group_reason": group.get("reason")})
    top = []
    for folder, count in by_group.most_common(max_groups):
        top.append({**examples[folder], "files": count})
    return {
        "review_by_mode": dict(sorted(by_mode.items())),
        "review_by_reason": dict(by_reason.most_common(8)),
        "review_top_groups": top,
        "review_groups_total": len(by_group),
    }


def queue_is_busy(api):
    """Wait until ordinary Shoko jobs finish before fallback manual linking."""
    queue = api.request("GET", "/Queue")
    if not isinstance(queue, dict):
        raise RuntimeError("Shoko /Queue did not return expected status")
    return (int(queue.get("TotalCount") or 0) > 0
            or int(queue.get("WaitingCount") or 0) > 0
            or int(queue.get("BlockedCount") or 0) > 0
            or bool(queue.get("CurrentlyExecuting")))


def run(api, *, state_path, plan_path, media_root="/Anime", catalog=None,
        minimum_age=900, now=None, do_apply=False):
    now = time.time() if now is None else now
    root = Path(media_root)
    if not root.is_dir() or not os.path.ismount(root):
        raise RuntimeError(f"Refusing to reconcile: {root} is not a mounted media directory")
    state_file = Path(state_path)
    old_state = json.loads(state_file.read_text()) if state_file.is_file() else {}
    unknown = api.unrecognized()
    current, eligible = stable_unknowns(
        unknown, old_state, now=now, media_root=root, minimum_age=minimum_age)
    _write_private_json(state_file, current)
    summary = {"currently_unrecognized": len(unknown),
               "mature_stable_unknown": len(eligible), "approved_for_auto": 0,
               "needs_review": 0, "submitted": 0}
    if not eligible:
        return summary
    if queue_is_busy(api):
        summary["shoko_queue_busy"] = True
        return summary
    plan = prepare(api, overrides={}, catalog=catalog, aggressive=False)
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
            result = apply(api, safe_plan, journal=str(Path(plan_path).with_suffix(".journal.json")))
            summary.update({"submitted": result["submitted"], "errors": result["errors"],
                            "awaiting_series_refresh": result["awaiting_series_refresh"],
                            "deferred": result["deferred"]})
    return summary


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default=os.getenv("SHOKO_URL", "http://127.0.0.1:8111"))
    parser.add_argument("--catalog")
    parser.add_argument("--media-root", default="/Anime")
    parser.add_argument("--state", default="/var/lib/shoko-reconcile/seen.json")
    parser.add_argument("--plan", default="/var/lib/shoko-reconcile/auto-plan.json")
    parser.add_argument("--minimum-age", type=int, default=900, metavar="SECONDS")
    parser.add_argument("--apply", action="store_true", help="Submit safe links, otherwise dry-run")
    parser.add_argument("--confirm", help="Must equal LINK for --apply")
    args = parser.parse_args(argv)
    if args.minimum_age < 60:
        parser.error("--minimum-age must be at least 60 seconds")
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
