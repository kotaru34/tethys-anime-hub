#!/usr/bin/env python3
"""One-pass, conservative resolution of the remaining 24 Shoko files.

The 24 exact File IDs and RelativePaths come from the operator's CT2601
snapshot after the earlier successful 21 XRef submissions. Only Shoko API
metadata is read; no /Anime file walk, no torrent edits, no auto-ignore.

Work metadata may be created ONLY for the two independently identified
DxD standalone OVAs (AniDB 11184, 11844). No blind link for those OVAs.
The existing Yuusha E13 -> AniDB S01 is verified against the known true
AniDB episode ID and title. Bonus OP/ED/PV XRefs are only written if the
actual, unique AniDB Credits/Trailer episode is *unambiguously* identified
by the filename/edition's explicit variant number and the work identity.

Automatic apply:
  python3 resolve_remaining24.py --apply --confirm LINK_VERIFIED_REMAINING_24 \
      --report /root/shoko-remaining24-report.json

Read-only:
  python3 resolve_remaining24.py --report /root/shoko-remaining24-dry-run.json
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
from resolve_45_onepass import build_expected
from targeted_metadata_bootstrap import atomic_json, exclusive_state_lock

STATE = Path("/var/lib/shoko-reconcile/resolve-remaining24-20261122.state.json")
PENDING_IDS = frozenset((
    3435,3430,3433,3432,3437,3438,3429,3439,3434,3431,
    2994,2999,2997,3018,3016,3017,3020,3008,3009,3005,3007,
    3209,3206,3222,
))
DAL_NCED = (3435,3430,3433,3432,3437,3438,3429,3439,3434,3431)
DAL_SOURCE_TV_EPISODES = (1,2,3,4,5,6,8,10,12,13)
# Publisher's Moozzi2 S1 Director's Cut bonus-list *rounding* in MiB.
# Used as release identity evidence, not a Shoko episode-number mapping.
DAL_SOURCE_SIZES_MIB = (100.7,55.8,83.5,63.7,101.0,90.1,60.7,60.8,61.5,99.5)
DAL_SOURCE = "https://nyaa.wiki/view/1939083"
WORK_MAP = {
    **{fid: 8808 for fid in DAL_NCED},
    2994:11261,2999:11992,2997:11992,
    3018:10691,3016:10691,3017:10691,3020:10691,
    3008:9409,3009:9409,3005:9409,3007:9409,
    3209:11184,3206:11844,3222:16917,
}
# The file order 03/04 alone is not proof of the correct OVA content.
DXD_OVA_WORKS = {
    3209: (11184, "High School DxD New: Teishi Kyoushitsu no Vampire"),
    3206: (11844, "High School DxD Born: Yomigaeranai Fushichou"),
}
ALLOWED_CREATE = frozenset((11184, 11844))
YUUSHA_EPISODE = {
    "kind":"Special", "number":1, "anidb_episode_id":256391,
    "title":"Remember, the Work Trip Is First and Foremost a Learning Opportunity (Part 1)",
}
# Explicit clip identity: no treating a PV as an opening or a TV episode.
CLIP_KINDS = {
    2994:("Trailer","PV",1),2999:("Trailer","PV",1),2997:("Trailer","PV",2),
    3018:("Credits","Ending",1),3016:("Credits","Opening",1),
    3017:("Credits","Opening",2),3020:("Trailer","PV",1),
    3008:("Credits","Ending",1),3009:("Credits","Ending",2),
    3005:("Credits","Opening",1),3007:("Credits","Opening",2),
}
for ordinal, fid in enumerate(DAL_NCED, start=1):
    CLIP_KINDS[fid] = ("Credits", "Ending", ordinal)


def pinned_paths():
    old, _ = build_expected()
    if len(PENDING_IDS) != 24 or set(WORK_MAP) != PENDING_IDS:
        raise ValueError("Invalid reviewed 24-file allowlist")
    return {fid:old[fid] for fid in sorted(PENDING_IDS)}


def load_state(path=STATE):
    if not path.exists():
        return {"schema":1, "metadata_attempts":{}, "xref_attempts":{}}
    data = json.loads(path.read_text(encoding="utf-8"))
    if (not isinstance(data, dict) or data.get("schema") != 1
        or not isinstance(data.get("metadata_attempts"), dict)
        or not isinstance(data.get("xref_attempts"), dict)
        or not set(data["metadata_attempts"]).issubset(
            {str(i) for i in ALLOWED_CREATE})
        or not set(data["xref_attempts"]).issubset(
            {str(i) for i in PENDING_IDS})):
        raise ValueError("Unrecognized or corrupt journal; no writes")
    return data


def current_unknown(api, expected):
    """One bounded page; reject an unexpected/incomplete response before POSTs."""
    r = api.request("GET", "/File",
                    {"include_only":"Unrecognized","pageSize":100,"page":1})
    if not isinstance(r,dict) or type(r.get("Total")) is not int or not isinstance(r.get("List"),list):
        raise ValueError("Shoko /File Unrecognized returned invalid response")
    if r["Total"] > 100 or r["Total"] != len(r["List"]):
        raise ValueError("Unrecognized listing changed or exceeded 100-file cap")
    paths, sizes = {}, {}
    for rec in r["List"]:
        fid = rec.get("ID")
        if type(fid) is not int or fid < 1 or fid in paths:
            raise ValueError("Invalid/duplicate Shoko File ID")
        paths[fid] = {x.get("RelativePath") for x in (rec.get("Locations") or [])
                      if isinstance(x,dict)}
        sizes[fid] = rec.get("Size")
    changed = [fid for fid,path in expected.items()
               if fid in paths and path not in paths[fid]]
    if changed:
        raise ValueError(f"Shoko RelativePath drift for File IDs {changed}: no writes")
    return paths,sizes,r["Total"]


def local_work(api, aid):
    data = api.local_series(aid)
    if data is None:
        return {"status":"missing","anidb_id":aid}
    ids = data.get("IDs") or {}
    sid = int(ids.get("ID") or 0)
    if sid < 1 or int(ids.get("AniDB") or 0) != aid:
        raise ValueError(f"Shoko local work mismatch for AniDB {aid}")
    return {"status":"present","anidb_id":aid,"shoko_series_id":sid}


def all_episode_index(api, sid):
    index = defaultdict(list)
    values = list(api.pages(f"/Series/{sid}/Episode", {
        "includeDataFrom":"AniDB","includeMissing":"True",
        "includeUnaired":"True","includeHidden":"True",
        "includeManuallyLinked":"True"},size=500))
    if len(values) > 240:
        raise ValueError(f"Too many AniDB episodes for Shoko Series {sid}")
    for rec in values:
        ep = rec.get("AniDB") or {}
        kind = str(ep.get("Type") or "")
        kind = ("Episode" if kind.casefold() in ("normal","episode")
                else "Special" if kind.casefold() in ("ova","ona","special")
                else kind.title())
        number = ep.get("EpisodeNumber")
        eid = ep.get("ID")
        title = ep.get("Title")
        if kind in ("Episode","Special","Credits","Trailer","Other","Parody") \
            and type(number) is int and number > 0 \
            and type(eid) is int and eid > 0 \
            and isinstance(title,str) and title.strip():
            index[kind].append({
                "type":kind,"number":number,
                "anidb_episode_id":eid,"title":title,
            })
    for kind in index:
        index[kind].sort(key=lambda x:x["number"])
    return dict(index)


def category_title(title, kind):
    """Return (category, version ordinal) from an unambiguous AniDB title.

    e.g. Opening 1a/1b => 1/2, Ending => 1, Ending 2 => 2,
         PV 01 => 1, Promotional Video 2 => 2.
    Do not accept arbitrarily named commercials or trailer variations.
    """
    raw = title.strip().casefold().replace("-", " ")
    if kind == "Opening":
        m = re.fullmatch(r"(?:opening|op)(?:\s+(?:1)?([ab]))?", raw)
        if m: return ("Opening", 1 if m.group(1) in (None,"a") else 2)
        m = re.fullmatch(r"(?:opening|op)\s+0?([1-9]\d*)", raw)
        if m: return ("Opening", int(m.group(1)))
    if kind == "Ending":
        m = re.fullmatch(r"(?:ending|ed)(?:\s+(?:1)?([ab]))?", raw)
        if m: return ("Ending", 1 if m.group(1) in (None,"a") else 2)
        m = re.fullmatch(r"(?:ending|ed)\s+0?([1-9]\d*)", raw)
        if m: return ("Ending", int(m.group(1)))
    if kind == "PV":
        m = re.fullmatch(
            r"(?:pv|promotional\s+video|promotional\s+video\s+pv)"
            r"(?:\s+0?([1-9]\d*))?",raw)
        if m:return ("PV",int(m.group(1) or 1))
    return None


def release_size_proven(fid, size):
    """Moozzi2 list supplies rounded MiB; allow 3% size difference."""
    if type(size) is not int or size < 1:
        return False
    ordinal = DAL_NCED.index(fid)
    reported = DAL_SOURCE_SIZES_MIB[ordinal]
    measured = size / 1048576
    return abs(measured - reported) <= max(0.7, 0.03 * reported)


def choose_clip(index, fid, size):
    target_kind, group, ordinal = CLIP_KINDS[fid]
    metadata = index.get(target_kind, [])
    # A source-edition match is required to trust Moozzi2 NCED numbering.
    if fid in DAL_NCED and not release_size_proven(fid,size):
        return None, "date_a_live_release_size_not_verified"
    candidates = [ep for ep in metadata
                  if category_title(ep["title"],group) == (group,ordinal)]
    if len(candidates) != 1:
        return None, "anidb_clip_variant_missing_or_ambiguous"
    # When there is only one numbered *file*, a simple "PV"/"Ending"
    # label may work; for multiple versions require distinct ordinal labels.
    if ordinal > 1:
        if category_title(candidates[0]["title"],group) != (group,ordinal):
            return None, "clip_ordinal_not_proven"
    # Do not map 10 different NCED files to one generic ending.
    return candidates[0], None


def ensure_no_duplicate_target(rows):
    """Two different clip files should never be silently collapsed to one AniDB bonus."""
    grouped = defaultdict(list)
    for row in rows.values():
        c = row.get("candidate")
        if c and row["status"] == "ready" and row["file_id"] != 3222:
            grouped[(c["anidb_id"],c["type"],c["number"],c["anidb_episode_id"])].append(row)
    for _, same in grouped.items():
        if len(same) > 1:
            for row in same:
                row["status"] = "duplicate_anidb_clip_target_needs_review"
                row.pop("candidate",None)


def run_once(api,state,*,apply=False,persist=lambda _:None,
             sleep=time.sleep,monotonic=time.monotonic,now=time.time,
             max_wait=60):
    paths = pinned_paths()
    unknown,sizes,total = current_unknown(api,paths)
    rows = {fid:{
        "file_id":fid,"path":path,"anidb_id":WORK_MAP[fid],
        "status":"pending" if fid in unknown else "already_not_unrecognized"
    } for fid,path in paths.items()}
    active = {fid for fid in PENDING_IDS if fid in unknown}
    report = {
        "mode":"apply" if apply else "dry_run",
        "total_unrecognized_at_start":total,
        "pinned_still_unrecognized":len(active),
        "metadata_requests_submitted":0,"xref_requests_submitted":0,
        "release_evidence_source":DAL_SOURCE,
        "date_a_live_nced_origin_episode_map":{
            str(fid):DAL_SOURCE_TV_EPISODES[i] for i,fid in enumerate(DAL_NCED)},
        "rows":rows,
    }
    works = {}
    for aid in sorted({WORK_MAP[fid] for fid in active}):
        works[aid] = local_work(api,aid)
    # Only create the two missing, explicitly titled DxD standalone OVAs.
    missing = [aid for aid in sorted(ALLOWED_CREATE)
               if aid in works and works[aid]["status"] == "missing"]
    if apply and missing:
        for aid in missing:
            if str(aid) in state["metadata_attempts"]:
                continue
            if report["metadata_requests_submitted"]:
                sleep(2)
            state["metadata_attempts"][str(aid)] = {
                "at":int(now()),"outcome":"dispatch_uncertain"}
            persist(state)
            try:
                api.refresh_series(aid)
            except Exception as exc:
                state["metadata_attempts"][str(aid)]["outcome"] = "request_error_uncertain"
                persist(state)
                report["metadata_error"] = f"{aid}: {type(exc).__name__}: {str(exc)[:200]}"
                break
            state["metadata_attempts"][str(aid)]["outcome"] = "requested"
            persist(state)
            report["metadata_requests_submitted"] += 1
        deadline = monotonic() + max_wait
        while monotonic() < deadline:
            pending = [aid for aid in missing if works[aid]["status"] == "missing"]
            if not pending:break
            sleep(min(5,max(0,deadline - monotonic())))
            for aid in pending:
                works[aid] = local_work(api,aid)
    report["work_status"] = {str(k):v for k,v in sorted(works.items())}
    indexes = {
        aid:all_episode_index(api,w["shoko_series_id"])
        for aid,w in works.items() if w["status"] == "present"
    }
    for fid in sorted(active):
        row = rows[fid]
        aid = WORK_MAP[fid]
        if aid not in indexes:
            row["status"] = "local_work_metadata_missing"
            continue
        if fid in DXD_OVA_WORKS:
            # These two files have ordinal names in a directory, but do
            # not contain the release title; record metadata, DO NOT guess.
            row["status"] = "dxd_ova_content_proof_required"
            row["candidate_ova_work_title"] = DXD_OVA_WORKS[fid][1]
            row["possible_episodes"] = indexes[aid].get("Episode",[])[:4]
            continue
        if fid == 3222:
            candidates = [ep for ep in indexes[aid].get("Special",[])
                          if ep["number"] == YUUSHA_EPISODE["number"]
                          and ep["anidb_episode_id"] == YUUSHA_EPISODE["anidb_episode_id"]
                          and ep["title"] == YUUSHA_EPISODE["title"]]
            if len(candidates) != 1:
                row["status"] = "yuusha_ova_special_identity_changed"
                continue
            chosen = candidates[0]
            row["evidence"] = "E13 after E01-E12 + exact previously verified AniDB S01 title and episode ID"
        else:
            chosen,reason = choose_clip(indexes[aid],fid,sizes.get(fid))
            row["possible_credits_or_trailers"] = [
                ep for kind in ("Credits","Trailer") for ep in indexes[aid].get(kind,[])
            ][:50]
            if fid in DAL_NCED:
                row["source_release_size_mib"] = DAL_SOURCE_SIZES_MIB[DAL_NCED.index(fid)]
                row["indexed_size_mib"] = (round(sizes[fid]/1048576,2)
                                           if type(sizes.get(fid)) is int else None)
            if chosen is None:
                row["status"] = reason
                continue
        row["candidate"] = {
            "anidb_id":aid,"shoko_series_id":works[aid]["shoko_series_id"],**chosen}
        row["status"] = (
            "previous_xref_attempt_verify_shoko" if str(fid) in state["xref_attempts"]
            else "ready")
    ensure_no_duplicate_target(rows)
    ready = [fid for fid in sorted(active) if rows[fid]["status"] == "ready"]
    # A second bounded query protects against recognition during metadata work.
    second_read = False
    if apply and ready:
        later,_,_ = current_unknown(api,paths)
        second_read = True
        for fid in ready:
            if fid not in later:
                rows[fid]["status"] = "automatically_recognized_skip"
        ready = [fid for fid in ready if fid in later]
    if apply:
        for fid in ready:
            target = rows[fid]["candidate"]
            state["xref_attempts"][str(fid)] = {
                "outcome":"dispatch_uncertain","at":int(now()),
                "anidb_id":target["anidb_id"],
                "anidb_episode_id":target["anidb_episode_id"]}
            persist(state)
            try:
                api.link(fid,target["shoko_series_id"],target["number"],target["type"])
            except Exception as exc:
                state["xref_attempts"][str(fid)]["outcome"] = "request_error_uncertain"
                persist(state)
                rows[fid]["status"] = "xref_request_error_uncertain"
                rows[fid]["error"] = f"{type(exc).__name__}: {str(exc)[:200]}"
                break
            state["xref_attempts"][str(fid)]["outcome"] = "submitted"
            persist(state)
            rows[fid]["status"] = "xref_submitted"
            report["xref_requests_submitted"] += 1
    report["counts"] = dict(Counter(row["status"] for row in rows.values()))
    report["scope"] = {
        "unrecognized_page_reads":1+int(second_read),
        "exact_anidb_works_read":len(works),
        "targeted_episode_list_reads":len(indexes),
        "max_metadata_creates":2,
        "full_shoko_file_scans":0,"media_walks":0,
        "torrent_writes":0,"auto_ignore_calls":0,"background_tasks":0}
    return report


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--url",default="http://127.0.0.1:8111")
    p.add_argument("--state",type=Path,default=STATE)
    p.add_argument("--report",type=Path,
                   default=Path("/root/shoko-remaining24-report.json"))
    p.add_argument("--apply",action="store_true")
    p.add_argument("--confirm",default="")
    p.add_argument("--max-wait",type=int,default=60)
    args = p.parse_args(argv)
    if args.apply and args.confirm != "LINK_VERIFIED_REMAINING_24":
        p.error("Apply requires --confirm LINK_VERIFIED_REMAINING_24")
    if args.max_wait < 0 or args.max_wait > 300:
        p.error("--max-wait must be 0..300")
    key = os.getenv("SHOKO_API_KEY")
    if not key:p.error("Set SHOKO_API_KEY")
    context = exclusive_state_lock(args.state) if args.apply else nullcontext()
    try:
        with context:
            state = load_state(args.state)
            report = run_once(ShokoAPI(args.url,key),state,apply=args.apply,
                              persist=lambda d:atomic_json(args.state,d),
                              max_wait=args.max_wait)
            atomic_json(args.report,report)
    except BlockingIOError:
        p.error("One-pass remaining-24 script already running")
    print("Report:",args.report)
    print("Result:",report["mode"],report["counts"],
          "metadata POSTs:",report["metadata_requests_submitted"],
          "XRef POSTs:",report["xref_requests_submitted"])
    print("Remaining review IDs:",
          [fid for fid,row in report["rows"].items()
           if row["status"] not in ("xref_submitted","automatically_recognized_skip",
                                   "already_not_unrecognized","ready")])
    return int(bool(report.get("metadata_error") or
                    report["counts"].get("xref_request_error_uncertain")))


if __name__ == "__main__":
    raise SystemExit(main())
