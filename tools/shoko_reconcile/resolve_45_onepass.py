#!/usr/bin/env python3
"""One-shot Shoko 45-file resolver: exact identity checks, safe writes only.

Never traverses /Anime, renames a torrent, globally enumerates recognized
files, or starts a watcher. This command checks ONE bounded page of currently
unrecognized files, resolves only pinned File IDs/RelativePaths, fetches exact
AniDB works/episodes, optionally creates a limited set of missing works, and
applies only unambiguous episode XRefs. Ambiguous credits, trailers and special
releases are reported rather than guessed. Journal persists *before* each POST.

  python3 resolve_45_onepass.py --apply --confirm RESOLVE_SAFE_XREFS_45 \
    --report /root/shoko-resolve-45.json
  # No write version:
  python3 resolve_45_onepass.py --report /root/shoko-resolve-45-dry-run.json
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from contextlib import nullcontext
import json
import os
from pathlib import Path
import re
import time

from shoko_reconcile import ShokoAPI
from targeted_metadata_bootstrap import atomic_json, exclusive_state_lock

STATE = Path("/var/lib/shoko-reconcile/resolve-45-20261122.state.json")
MAX_UNRECOGNIZED = 100
# Date A Live first-season TV (12), then a separately catalogued Date to Date
# OVA (release file 13). Also an earlier separately downloaded copy of OVA.
DAL_TV_AID = 8808
DAL_OVA_AID = 9734
DAL_EPISODE_FIDS = (
    3423,3427,3425,3424,3419,3417,3422,3416,3428,3418,3420,3421,3426,
)
DAL_NCED_FIDS = (3435,3430,3433,3432,3437,3438,3429,3439,3434,3431)
DAL_NCOP_FID = 3436
DAL_FOLDER = "[Moozzi2] Date A Live Director's Cut Edition [BDRip 1920x1080 x264 FLAC]"
DAL_SUFFIX = "[BDRip 1920x1080 x264 FLAC].mkv"
# Explicitly verified exact standalone OVA/media works from previous review.
STANDALONES = {
    2955: (9734, "Episode", 1),
    2957: (10568, "Episode", 1),
    3374: (15807, "Episode", 1),
    3023: (14782, "Episode", 1),
    2253: (15329, "Episode", 1),
}
# OVA3/4 are not confidently identified to specific editions from filename,
# and TV E13 of Yuusha is not a valid AniDB E13. Never guess.
SPECIAL_REVIEW = {
    3209: "DxD OVA - 03: distinct OVA work 11184 is plausible, but source/content identity is unverified",
    3206: "DxD OVA - 04: distinct OVA work 11844 is plausible, but source/content identity is unverified",
    3222: "Yuusha, Yamemasu - 13 is not an AniDB TV E13; determine whether it is S01-S04 or other content",
}
# Only create absent works with exact independent release identity. The TV
# entry is included to handle an unexpectedly absent local work.
CREATABLE_AIDS = frozenset((8808, 9734, 10568, 15807, 14782, 15329))
# Existing local work IDs for additional OP/ED/PV inspection (never create them).
CREDIT_WORKS = {
    3436: 8808, **{fid: 8808 for fid in DAL_NCED_FIDS},
    2993: 11261, 2995: 11261, 2994: 11261,
    2999: 11992, 2997: 11992,
    3016: 10691, 3017: 10691, 3018: 10691, 3020: 10691,
    3005: 9409, 3007: 9409, 3008: 9409, 3009: 9409,
}
# Only safe when the entire work has exactly one matching category of
# Credits and no variants; PVs and numbered multi-variant extras are held.
UNIQUE_CREDIT_FIDS = frozenset((2993, 2995, 3436))
TARGETED_AIDS = frozenset({DAL_TV_AID, DAL_OVA_AID}
                          | {x[0] for x in STANDALONES.values()}
                          | set(CREDIT_WORKS.values()))
KNOWN_EPISODE_TYPES = {"Episode", "Special", "Other", "Credits", "Trailer", "Parody"}


def build_expected():
    paths, targets = {}, {}
    for number, fid in enumerate(DAL_EPISODE_FIDS, 1):
        paths[fid] = (
            f"{DAL_FOLDER}/[Moozzi2] Date A Live Director's Cut - "
            f"{number:02d} {DAL_SUFFIX}")
        targets[fid] = (DAL_TV_AID, "Episode", number) if number <= 12 else (
            DAL_OVA_AID, "Episode", 1)
    for n, fid in enumerate(DAL_NCED_FIDS, 1):
        paths[fid] = f"{DAL_FOLDER}/NC/[Moozzi2] Date A Live NCED - {n:02d} {DAL_SUFFIX}"
    paths[DAL_NCOP_FID] = f"{DAL_FOLDER}/NC/[Moozzi2] Date A Live NCOP - 01 {DAL_SUFFIX}"
    other = {
        2995: "[Kawaiika-Raws] (2016) KonoSuba S1 [BDRip 1920x1080 HEVC FLAC]/Bonus/[Kawaiika-Raws] KonoSuba S1ED [BDRip 1920x1080 HEVC FLAC].mkv",
        2993: "[Kawaiika-Raws] (2016) KonoSuba S1 [BDRip 1920x1080 HEVC FLAC]/Bonus/[Kawaiika-Raws] KonoSuba S1OP [BDRip 1920x1080 HEVC FLAC].mkv",
        2994: "[Kawaiika-Raws] (2016) KonoSuba S1 [BDRip 1920x1080 HEVC FLAC]/Bonus/[Kawaiika-Raws] KonoSuba S1PV [BDRip 1920x1080 HEVC FLAC].mkv",
        2999: "[Kawaiika-Raws] (2017) KonoSuba S2 [BDRip 1920x1080 HEVC FLAC]/Bonus/[Kawaiika-Raws] KonoSuba S2PV1 [BDRip 1920x1080 HEVC FLAC].mkv",
        2997: "[Kawaiika-Raws] (2017) KonoSuba S2 [BDRip 1920x1080 HEVC FLAC]/Bonus/[Kawaiika-Raws] KonoSuba S2PV2 [BDRip 1920x1080 HEVC FLAC].mkv",
        2957: "[Moozzi2] Date A Live II Kurumi Star Festival [BDRip 1920x1080 x264 FLAC]/[Moozzi2] Date A Live II - Kurumi Star Festival [BDRip 1920x1080 x264 FLAC].mkv",
        3374: "[NanDesuKa] Kaguya-sama wa Kokurasetai - OVA [WEBRip 1080p x264 AAC]/[NanDesuKa] Kaguya-sama wa Kokurasetai - OVA [WEBRip 1080p x264 AAC].mkv",
        3018: "[Snow-Raws] High School DxD Born [BDRip 1920x1080 HEVC FLAC]/NC/[Snow-Raws] High School DxD BorN ED - 01 [BDRip 1920x1080 HEVC FLAC].mkv",
        3016: "[Snow-Raws] High School DxD Born [BDRip 1920x1080 HEVC FLAC]/NC/[Snow-Raws] High School DxD BorN OP - 01 [BDRip 1920x1080 HEVC FLAC].mkv",
        3017: "[Snow-Raws] High School DxD Born [BDRip 1920x1080 HEVC FLAC]/NC/[Snow-Raws] High School DxD BorN OP - 02 [BDRip 1920x1080 HEVC FLAC].mkv",
        3020: "[Snow-Raws] High School DxD Born [BDRip 1920x1080 HEVC FLAC]/NC/[Snow-Raws] High School DxD BorN PV [BDRip 1920x1080 HEVC FLAC].mkv",
        3008: "[Snow-Raws] High School DxD New [BDRip 1920x1080 HEVC FLAC]/NC/[Snow-Raws] High School DxD New ED - 01 [BDRip 1920x1080 HEVC FLAC].mkv",
        3009: "[Snow-Raws] High School DxD New [BDRip 1920x1080 HEVC FLAC]/NC/[Snow-Raws] High School DxD New ED - 02 [BDRip 1920x1080 HEVC FLAC].mkv",
        3005: "[Snow-Raws] High School DxD New [BDRip 1920x1080 HEVC FLAC]/NC/[Snow-Raws] High School DxD New OP - 01 [BDRip 1920x1080 HEVC FLAC].mkv",
        3007: "[Snow-Raws] High School DxD New [BDRip 1920x1080 HEVC FLAC]/NC/[Snow-Raws] High School DxD New OP - 02 [BDRip 1920x1080 HEVC FLAC].mkv",
        3023: "Goblin_Slayer_Goblin's_Crown_[AniLibria_TV]_[BDRip_1080p_HEVC].mkv",
        2253: "Єдина, хто кохає Великого Мене - це ти! - OVA [1080p](Субтитри).mkv",
        2955: "Date a Live OVA [BD] [720p]/Date a Live OVA [BDRip, 720p, Hi10p, Vorbis].mkv",
        3209: "High School DxD OVA [BDRip 1080p]/High School DxD OVA - 03 (BDRip 1920x1080).mkv",
        3206: "High School DxD OVA [BDRip 1080p]/High School DxD OVA - 04 (BDRip 1920x1080).mkv",
        3222: "Yuusha, Yamemasu/Yuusha, Yamemasu - 13.mkv",
    }
    paths.update(other)
    targets.update(STANDALONES)
    if len(paths) != 45 or len(set(paths)) != 45:
        raise ValueError("Unexpected 45-file frozen allowlist")
    if len(targets) != 18:
        raise ValueError("Unexpected safe 18-episode mapping")
    if not set(targets).issubset(paths) or not set(CREDIT_WORKS).issubset(paths):
        raise ValueError("Misconfigured mapping")
    return paths, targets


def load_state(path=STATE):
    if not path.exists():
        return {"schema": 1, "metadata_attempts": {}, "xref_attempts": {}}
    state = json.loads(path.read_text(encoding="utf-8"))
    paths, _ = build_expected()
    if (state.get("schema") != 1
            or not isinstance(state.get("metadata_attempts"), dict)
            or not isinstance(state.get("xref_attempts"), dict)
            or not set(state["metadata_attempts"]).issubset(
                {str(aid) for aid in CREATABLE_AIDS})
            or not set(state["xref_attempts"]).issubset(
                {str(fid) for fid in paths})):
        raise ValueError("Invalid persistent journal; no requests sent")
    return state


def snapshot(api, expected):
    payload = api.request("GET", "/File", {
        "include_only": "Unrecognized", "pageSize": MAX_UNRECOGNIZED,
        "page": 1})
    if (not isinstance(payload, dict) or type(payload.get("Total")) is not int
            or not isinstance(payload.get("List"), list)):
        raise ValueError("Invalid one-page Shoko unrecognized response")
    rows = payload["List"]
    if payload["Total"] > MAX_UNRECOGNIZED or len(rows) != payload["Total"]:
        raise ValueError("Unrecognized count exceeds 100 or changed during fetch; no writes")
    unrecognized = {}
    for row in rows:
        fid = row.get("ID")
        if type(fid) is not int or fid in unrecognized:
            raise ValueError("Invalid/duplicate File ID in unrecognized response")
        unrecognized[fid] = {
            loc.get("RelativePath") for loc in row.get("Locations") or []
            if isinstance(loc, dict)
        }
    drift = [
        fid for fid, path in expected.items()
        if fid in unrecognized and path not in unrecognized[fid]
    ]
    if drift:
        raise ValueError(f"Exact pinned RelativePath changed for File IDs {drift}; no writes")
    return unrecognized, payload["Total"]


def inspect_work(api, aid):
    series = api.local_series(aid)
    if not series:
        return {"status": "missing", "anidb_id": aid}
    ids = series.get("IDs") or {}
    sid, actual = int(ids.get("ID") or 0), int(ids.get("AniDB") or 0)
    if sid <= 0 or actual != aid:
        raise ValueError(f"AniDB {aid} returned unexpected Shoko local work identity")
    return {"status": "present", "anidb_id": aid, "shoko_series_id": sid}


def episode_index(api, sid):
    records = list(api.pages(f"/Series/{sid}/Episode", {
        "includeDataFrom": "AniDB", "includeMissing": "True",
        "includeUnaired": "True", "includeHidden": "True",
        "includeManuallyLinked": "True"}, size=500))
    if len(records) > 240:
        raise ValueError(f"Too many episodes for Shoko series {sid}")
    result = defaultdict(list)
    for record in records:
        value = record.get("AniDB") or {}
        kind = str(value.get("Type") or "")
        if kind.casefold() in ("normal", "episode"):
            kind = "Episode"
        elif kind.casefold() in ("ova", "ona"):
            kind = "Special"
        else:
            kind = kind.title()
        ep = value.get("EpisodeNumber")
        eid = value.get("ID")
        if (kind in KNOWN_EPISODE_TYPES and type(ep) is int and ep > 0
                and type(eid) is int and eid > 0
                and isinstance(value.get("Title"), str) and value["Title"]):
            result[(kind, ep)].append({
                "type": kind, "number": ep,
                "anidb_episode_id": eid, "title": value["Title"][:260],
            })
    return result


def unique_credit(index, fid):
    """Only a unique, non-variant OP/ED in the *entire* series may match."""
    if fid not in UNIQUE_CREDIT_FIDS:
        return None, "extra_variant_or_pv_needs_clip_identity"
    wants_opening = fid in (2993, 3436)
    title_pattern = re.compile(r"(?i)^(opening|op)(?:\s*1)?$")
    if not wants_opening:
        title_pattern = re.compile(r"(?i)^(ending|ed)(?:\s*1)?$")
    candidates = [
        ep for (kind, _), records in index.items()
        if kind == "Credits"
        for ep in records if title_pattern.fullmatch(ep["title"].strip())
    ]
    # Deliberately reject any other variant in that category (including 1a/b,
    # ending 2, etc.) even if the regex matched one of them.
    whole_category = [
        ep for (kind, _), records in index.items() if kind == "Credits"
        for ep in records if (re.match(r"(?i)^(opening|op)", ep["title"].strip())
                              if wants_opening else
                              re.match(r"(?i)^(ending|ed)", ep["title"].strip()))
    ]
    if len(candidates) == 1 and len(whole_category) == 1:
        return candidates[0], None
    return None, "credits_not_uniquely_proven_in_anidb"


def prepare(api, state, *, apply=False, max_wait=120, interval=5,
            sleep=time.sleep, monotonic=time.monotonic,
            persist=lambda _: None, now=time.time):
    expected, targets = build_expected()
    unrecognized, current_total = snapshot(api, expected)
    rows = {
        fid: {"file_id": fid, "path": path,
              "status": "already_not_unrecognized" if fid not in unrecognized
                        else "unresolved"}
        for fid, path in expected.items()
    }
    report = {
        "mode": "apply" if apply else "dry_run",
        "total_unrecognized_at_start": current_total,
        "pinned_file_count": len(expected),
        "pinned_still_unrecognized": sum(fid in unrecognized for fid in expected),
        "other_unrecognized_not_in_pinned_set": sorted(
            fid for fid in unrecognized if fid not in expected),
        "metadata_requests_submitted": 0,
        "xref_requests_submitted": 0,
        "rows": rows,
    }
    active = {fid for fid in expected if fid in unrecognized}
    # Always annotate the exact technical reason instead of asking the
    # operator to run different scripts for every work.
    aids = sorted({targets[fid][0] for fid in targets if fid in active}
                  | {CREDIT_WORKS[fid] for fid in CREDIT_WORKS if fid in active})
    works = {}
    for aid in aids:
        works[aid] = inspect_work(api, aid)
    # No POST if a single targeted GET returned inconsistent identities.
    pending = sorted(aid for aid, work in works.items()
                     if work["status"] == "missing" and aid in CREATABLE_AIDS)
    if apply and pending:
        for aid in pending:
            if str(aid) in state["metadata_attempts"]:
                continue
            if report["metadata_requests_submitted"]:
                sleep(2)
            state["metadata_attempts"][str(aid)] = {
                "outcome": "dispatch_uncertain", "at": int(now())}
            persist(state)
            try:
                api.refresh_series(aid)
            except Exception as exc:
                state["metadata_attempts"][str(aid)]["outcome"] = (
                    "request_error_uncertain")
                persist(state)
                report["metadata_error"] = f"AniDB {aid}: {type(exc).__name__}: {str(exc)[:220]}"
                break
            state["metadata_attempts"][str(aid)]["outcome"] = "requested"
            persist(state)
            report["metadata_requests_submitted"] += 1
        # A bounded one-shot wait for the *specific* newly created works only.
        # No background job or periodic monitoring survives this process.
        deadline = monotonic() + max_wait
        while monotonic() < deadline:
            missing = [aid for aid in pending if works[aid]["status"] == "missing"]
            if not missing:
                break
            sleep(min(interval, max(0, deadline - monotonic())))
            for aid in missing:
                works[aid] = inspect_work(api, aid)
    report["work_status"] = {str(k): v for k, v in sorted(works.items())}
    index = {aid: episode_index(api, work["shoko_series_id"])
             for aid, work in works.items() if work["status"] == "present"}
    to_link = []
    for fid in sorted(active):
        row = rows[fid]
        if fid in targets:
            aid, kind, n = targets[fid]
            row["intended"] = {"anidb_id": aid, "type": kind, "number": n}
            if aid not in index:
                row["status"] = "waiting_for_work_metadata"
                continue
            matches = index[aid].get((kind, n), [])
            if len(matches) != 1:
                row["status"] = "missing_or_ambiguous_anidb_episode"
                continue
            episode = matches[0]
        elif fid in CREDIT_WORKS:
            aid = CREDIT_WORKS[fid]
            row["intended"] = {"anidb_id": aid, "category": "OP/ED/PV"}
            if aid not in index:
                row["status"] = "credit_work_metadata_missing"
                continue
            episode, reason = unique_credit(index[aid], fid)
            if episode is None:
                row["status"] = reason
                row["possible_credits_or_trailers"] = [
                    ep for (kind, _), eps in index[aid].items()
                    if kind in ("Credits", "Trailer") for ep in eps
                ][:35]
                continue
        else:
            row["status"] = "requires_content_identity"
            row["reason"] = SPECIAL_REVIEW.get(fid, "manual_content_review_required")
            continue
        row["candidate"] = {
            "anidb_id": aid, "shoko_series_id": works[aid]["shoko_series_id"],
            **episode,
        }
        if str(fid) in state["xref_attempts"]:
            row["status"] = "xref_previously_attempted_verify_in_shoko"
        else:
            row["status"] = "ready"
            to_link.append(fid)
    # Shoko's ordinary reconciler may independently recognize files while
    # metadata is loading. Refresh ONE bounded unrecognized page just before
    # any XRef POST, and never override an automatic match in that window.
    # This preserves the older manual_review_batch "not_unrecognized_skip"
    # behavior even when the server's metadata job finishes mid-operation.
    second_unrecognized_read = False
    if apply and to_link:
        current_unknown, _ = snapshot(api, expected)
        second_unrecognized_read = True
        for fid in to_link:
            if fid not in current_unknown:
                rows[fid]["status"] = "already_not_unrecognized_after_metadata"
        to_link = [fid for fid in to_link if fid in current_unknown]
    # The one-shot can safely complete all metadata-independent links
    # even when a different work is still pending in Shoko's internal queue.
    if apply:
        for fid in to_link:
            row = rows[fid]
            episode = row["candidate"]
            state["xref_attempts"][str(fid)] = {
                "outcome": "dispatch_uncertain",
                "at": int(now()), "anidb_id": episode["anidb_id"],
                "anidb_episode_id": episode["anidb_episode_id"]}
            persist(state)
            try:
                api.link(fid, episode["shoko_series_id"], episode["number"],
                         episode["type"])
            except Exception as exc:
                state["xref_attempts"][str(fid)]["outcome"] = (
                    "request_error_uncertain")
                persist(state)
                row["status"] = "xref_request_error_uncertain"
                row["error"] = f"{type(exc).__name__}: {str(exc)[:220]}"
                break
            state["xref_attempts"][str(fid)]["outcome"] = "submitted"
            persist(state)
            row["status"] = "xref_submitted"
            report["xref_requests_submitted"] += 1
    report["counts"] = dict(Counter(row["status"] for row in rows.values()))
    report["scope"] = {
        "unrecognized_file_page_gets": 1 + int(second_unrecognized_read),
        "known_work_ids_queried": aids,
        "targeted_episode_inventories": len(index),
        "max_metadata_posts": len(CREATABLE_AIDS),
        "max_xref_posts": len(expected),
        "full_library_scan": 0, "media_walks": 0,
        "filesystem_writes_to_anime": 0, "background_timers": 0,
    }
    # Easy-to-read terminal summary; full rows saved in report.
    report["manual_review_files"] = [
        {"file_id": row["file_id"], "status": row["status"],
         "reason": row.get("reason")}
        for row in rows.values()
        if row["status"] not in ("xref_submitted", "ready",
                                  "already_not_unrecognized")
    ]
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://127.0.0.1:8111")
    parser.add_argument("--state", type=Path, default=STATE)
    parser.add_argument("--report", type=Path, default=Path("/root/shoko-resolve-45.json"))
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--confirm", default="")
    parser.add_argument("--max-wait", type=int, default=120,
                        help="Maximum seconds to poll specific newly created AniDB works")
    args = parser.parse_args(argv)
    if args.apply and args.confirm != "RESOLVE_SAFE_XREFS_45":
        parser.error("Applying requires --confirm RESOLVE_SAFE_XREFS_45")
    if args.max_wait < 0 or args.max_wait > 600:
        parser.error("--max-wait must be 0..600 seconds")
    key = os.getenv("SHOKO_API_KEY")
    if not key:
        parser.error("Export SHOKO_API_KEY first")
    api = ShokoAPI(args.url, key)
    context = exclusive_state_lock(args.state) if args.apply else nullcontext()
    try:
        with context:
            state = load_state(args.state)
            report = prepare(api, state, apply=args.apply, max_wait=args.max_wait,
                             persist=lambda x: atomic_json(args.state, x))
            atomic_json(args.report, report)
    except BlockingIOError:
        parser.error("Another one-pass Shoko resolver holds the state lock")
    print("Report:", args.report)
    print("Result:", report["mode"], report["counts"],
          "metadata POSTs:", report["metadata_requests_submitted"],
          "XRef POSTs:", report["xref_requests_submitted"])
    if report["manual_review_files"]:
        print("Unresolved identity/metadata IDs:",
              [f["file_id"] for f in report["manual_review_files"]])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
