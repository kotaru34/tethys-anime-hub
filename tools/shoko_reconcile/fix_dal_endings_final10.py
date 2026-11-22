#!/usr/bin/env python3
"""Final Date A Live NCED correction: 4 new links + 3 protected repairs.

The previous 24-file batch incorrectly treated AniDB Ending titles as the
sequential NCED ordinal, skipping Ending 2a/2b/2c/2d. The nine actual TV
Credits entries are C02..C10. Match the nine edition-specific NCED files
in order to those nine Credits, with exact known ID/title/size checks.

IMPORTANT: This does not "recognize" four KonoSuba/DxD PV clips that have
no corresponding AniDB PV entry, or two numbered DxD OVAs whose content
identity has not been independently proven. Those six are reported.

One command applies all seven verified changes and writes one final report:
  python3 fix_dal_endings_final10.py --apply \
      --confirm CORRECT_DAL_NCED_XREFS_9 \
      --report /root/shoko-final10-correction.json

The default without --apply is read-only. It neither walks nor writes /Anime.
For every known already-recognized MKV, the endpoint
GET /File/{id}?include=XRefs is used (NOT includeXRefs=true), and replacement
is allowed only when the current AniDB episode ID equals the old *specific*
incorrect value from the prior report. Unknown/changed links fail closed.
"""
from __future__ import annotations

import argparse
from collections import Counter
from contextlib import nullcontext
import json
import os
from pathlib import Path
import shutil
import subprocess
import time

from shoko_reconcile import ShokoAPI
from resolve_45_onepass import build_expected
from targeted_metadata_bootstrap import atomic_json, exclusive_state_lock

STATE = Path("/var/lib/shoko-reconcile/fix-dal-nced-final10-20261122.state.json")
AID = 8808
SID = 280
# (NCED ordinal, Shoko File ID, AniDB Credits number, AniDB episode ID,
#  exact AniDB title, known Moozzi2 release filesize in MiB,
#  old incorrect AniDB episode ID if earlier XRef needs replacement).
ENDINGS = (
    (1, 3435, 2, 148984, "Ending 1", 100.7, None),
    (2, 3430, 3, 149639, "Ending 2a", 55.8, None),
    (3, 3433, 4, 149748, "Ending 3", 83.5, None),
    (4, 3432, 5, 154716, "Ending 2b", 63.7, 150419),
    (5, 3437, 6, 150419, "Ending 4", 101.0, 150418),
    (6, 3438, 7, 150418, "Ending 5", 90.1, 156907),
    (7, 3429, 8, 154715, "Ending 2c", 60.7, None),
    (8, 3439, 9, 154714, "Ending 2d", 60.8, None),
    (9, 3434, 10, 156907, "Ending 6", 61.5, None),
)
UNRESOLVED = {
    2994: "KonoSuba S1 PV: AniDB has Trailer '2nd Season Announcement', not a verified matching S1 PV",
    2997: "KonoSuba S2 PV2: no Trailer entry in work 11992",
    2999: "KonoSuba S2 PV1: no Trailer entry in work 11992",
    3020: "High School DxD BorN PV: no Trailer entry in work 10691",
    3209: "High School DxD OVA 03: possible work 11184 E01, AniDB Episode ID 161394; content unverified",
    3206: "High School DxD OVA 04: possible work 11844 E01, AniDB Episode ID 167801; content unverified",
}
EXPECTED_BY_FID = {entry[1]:entry for entry in ENDINGS}
EXPECTED_PATHS = {fid:path for fid,path in build_expected()[0].items()
                  if fid in EXPECTED_BY_FID or fid in UNRESOLVED}


def load_state(path=STATE):
    if not path.exists():
        return {"schema": 1, "attempts": {}}
    data = json.loads(path.read_text(encoding="utf-8"))
    if (not isinstance(data, dict) or data.get("schema") != 1
            or not isinstance(data.get("attempts"), dict)
            or not set(data["attempts"]).issubset(
                {str(fid) for fid in EXPECTED_BY_FID})):
        raise ValueError("Unknown/corrupt exact XRef correction journal")
    return data


def get_file(api, fid):
    """Correct Shoko 5.3.x syntax: ?include=XRefs, not ?includeXRefs=true."""
    value = api.request("GET", f"/File/{fid}", {"include": "XRefs"})
    if not isinstance(value, dict) or value.get("ID") != fid:
        raise ValueError(f"File ID {fid} missing or invalid")
    if "SeriesIDs" not in value or not isinstance(value["SeriesIDs"], list):
        raise ValueError(f"File {fid} missing SeriesIDs in XRefs response")
    if EXPECTED_PATHS[fid] not in {
        loc.get("RelativePath") for loc in value.get("Locations") or []
        if isinstance(loc, dict)
    }:
        raise ValueError(f"File {fid} exact relative path has changed")
    return value


def current_refs(value):
    """Return only AniDB work/episode pairs; reject malformed XRefs."""
    pairs = []
    for series in value["SeriesIDs"]:
        sid = (series.get("SeriesID") or {}).get("AniDB")
        epids = series.get("EpisodeIDs")
        if type(sid) is not int or not isinstance(epids, list):
            raise ValueError("Unexpected AniDB cross-reference structure")
        for ep in epids:
            eid = ep.get("AniDB")
            if type(eid) is not int or eid < 1:
                raise ValueError("Unexpected AniDB episode XRef ID")
            pairs.append((sid,eid))
    return pairs


def ending_size_matches(size, mib):
    return type(size) is int and abs(size/1048576 - mib) <= max(0.7,0.03*mib)


def check_episode_inventory(api):
    work = api.local_series(AID)
    ids = (work or {}).get("IDs") or {}
    if int(ids.get("ID") or 0) != SID or int(ids.get("AniDB") or 0) != AID:
        raise ValueError("Date A Live first-season Shoko/AniDB identity changed")
    entries = list(api.pages(f"/Series/{SID}/Episode", {
        "includeDataFrom":"AniDB", "includeMissing":"True",
        "includeUnaired":"True", "includeHidden":"True",
        "includeManuallyLinked":"True"}, size=500))
    if len(entries) > 240:
        raise ValueError("Unexpectedly large episode inventory")
    credits = {}
    for row in entries:
        source = row.get("AniDB") or {}
        if source.get("Type") != "Credits":
            continue
        n = source.get("EpisodeNumber")
        credits.setdefault(n,[]).append({
            "id":source.get("ID"),"title":source.get("Title")})
    if set(credits) != set(range(1,11)):
        raise ValueError("Date A Live AniDB credits inventory has unexpected gaps/variants")
    if credits[1] != [{"id":148985,"title":"Opening"}]:
        raise ValueError("Date A Live opening credit changed")
    for ordinal,fid,number,eid,title,_,_ in ENDINGS:
        if credits[number] != [{"id":eid,"title":title}]:
            raise ValueError(f"NCED {ordinal:02d} source AniDB Credits C{number:02d} changed")
    return credits


def unknown_list(api):
    response = api.request("GET","/File",{
        "include_only":"Unrecognized","pageSize":100,"page":1})
    if (not isinstance(response,dict) or type(response.get("Total")) is not int
            or not isinstance(response.get("List"),list)
            or response["Total"] > 100
            or len(response["List"]) != response["Total"]):
        raise ValueError("Invalid or truncated bounded Unrecognized listing")
    return {row["ID"] for row in response["List"]}


def inspection(api,state):
    check_episode_inventory(api)
    unknown = unknown_list(api)
    rows = {}
    for ordinal,fid,num,eid,title,size_mib,old_eid in ENDINGS:
        data = get_file(api,fid)
        refs = current_refs(data)
        row = {"file_id":fid,"ordinal":ordinal,
               "expected_relative_path":EXPECTED_PATHS[fid],
               "target":{"anidb_id":AID,"shoko_series_id":SID,
                         "type":"Credits","episode":num,
                         "anidb_episode_id":eid,"title":title},
               "existing_xrefs":refs,"indexed_size_bytes":data.get("Size")}
        if not ending_size_matches(data.get("Size"),size_mib):
            row.update(status="blocked",reason="release_file_size_does_not_match")
        elif refs == [(AID,eid)]:
            row["status"] = "already_correct"
        elif str(fid) in state["attempts"]:
            row["status"] = "previously_attempted_inspect_manually"
        elif old_eid is not None and refs == [(AID,old_eid)] and fid not in unknown:
            row.update(status="ready_correction",previous_anidb_episode_id=old_eid)
        elif old_eid is None and refs == [] and fid in unknown:
            row["status"] = "ready_new_link"
        else:
            row.update(status="blocked",reason="xref_state_is_not_the_exact_expected_old_link")
        rows[fid] = row
    other = {}
    for fid,note in UNRESOLVED.items():
        try:
            file = get_file(api,fid)
            refs = current_refs(file)
            other[fid] = {"file_id":fid,"reason":note,
                          "existing_xrefs":refs,
                          "status":"no_verified_anidb_target" if fid in unknown
                                   else "already_not_unrecognized"}
        except Exception as exc:
            other[fid] = {"file_id":fid,"reason":note,
                          "status":"audit_error",
                          "error":f"{type(exc).__name__}: {str(exc)[:180]}"}
    return rows,other


def apply_safe(api,state,persist):
    rows,other=inspection(api,state)
    report={"mode":"apply", "rows":rows,"other_unresolved":other,
            "submitted":0,"verified_after_write":0}
    # Preflight all nine first, especially the 3 previously wrong links.
    if any(row["status"] == "blocked" for row in rows.values()):
        report["mode"]="apply_aborted_unexpected_existing_xrefs"
        return finalize(report)
    for _,fid,num,eid,_,_,old_eid in ENDINGS:
        row=rows[fid]
        if row["status"] not in ("ready_new_link","ready_correction"):
            continue
        # Final just-in-time inspection before any replacement.
        latest = get_file(api,fid)
        refs = current_refs(latest)
        expected_refs = [(AID,old_eid)] if old_eid is not None else []
        if refs == [(AID,eid)]:
            row["status"]="already_correct_during_run"
            continue
        if refs != expected_refs:
            row.update(status="blocked_during_run",
                       reason="xref_changed_between_preflight_and_post")
            report["mode"]="apply_interrupted_unexpected_xrefs"
            break
        state["attempts"][str(fid)] = {
            "at":int(time.time()), "outcome":"dispatch_uncertain",
            "old":old_eid,"new":eid}
        persist(state)
        try:
            api.link(fid,SID,num,"Credits")
        except Exception as exc:
            state["attempts"][str(fid)]["outcome"]="request_error_uncertain"
            persist(state)
            row.update(status="request_error_uncertain",
                       error=f"{type(exc).__name__}: {str(exc)[:180]}")
            report["mode"]="apply_interrupted_uncertain"
            break
        report["submitted"] += 1
        try:
            seen = current_refs(get_file(api,fid))
        except Exception as exc:
            seen = []
            row["verification_error"]=f"{type(exc).__name__}: {str(exc)[:180]}"
        if seen != [(AID,eid)]:
            state["attempts"][str(fid)]["outcome"]="submitted_unverified"
            persist(state)
            row["status"]="submitted_unverified"
            report["mode"]="apply_interrupted_unverified"
            break
        state["attempts"][str(fid)]["outcome"]="verified"
        persist(state)
        row["status"]="xref_verified_corrected" if old_eid is not None \
                      else "xref_verified_new"
        report["verified_after_write"]+=1
    return finalize(report)


def finalize(report):
    report["counts"] = dict(Counter(
        row["status"] for row in report["rows"].values()))
    report["remaining_candidates"] = [
        f for f,row in report["rows"].items()
        if row["status"] not in ("already_correct",
                                "already_correct_during_run",
                                "xref_verified_corrected","xref_verified_new")
    ]
    report["scope"]={
        "pinned_tv_nced_files":9,
        "bonus_media_pending_without_verified_anidb_target":6,
        "full_library_scans":0,"media_walks":0,
        "torrent_file_edits":0,"auto_ignore":0,
        "background_jobs":0,
        "xref_inspection_endpoint":"GET /File/{id}?include=XRefs"}
    return report


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--url",default="http://127.0.0.1:8111")
    p.add_argument("--state",type=Path,default=STATE)
    p.add_argument("--report",type=Path,
                   default=Path("/root/shoko-final10-correction.json"))
    p.add_argument("--apply",action="store_true")
    p.add_argument("--confirm",default="")
    a=p.parse_args(argv)
    if a.apply and a.confirm!="CORRECT_DAL_NCED_XREFS_9":
        p.error("Use --confirm CORRECT_DAL_NCED_XREFS_9")
    key=os.getenv("SHOKO_API_KEY")
    if not key:p.error("Set SHOKO_API_KEY")
    context=exclusive_state_lock(a.state) if a.apply else nullcontext()
    try:
        with context:
            state=load_state(a.state)
            api=ShokoAPI(a.url,key)
            if a.apply:
                report=apply_safe(api,state,
                                  lambda s:atomic_json(a.state,s))
            else:
                rows,other=inspection(api,state)
                report=finalize({"mode":"dry_run", "rows":rows,
                                 "other_unresolved":other,
                                 "submitted":0,"verified_after_write":0})
            atomic_json(a.report,report)
    except BlockingIOError:
        p.error("Another correction process holds the lock")
    print("Report:",a.report)
    print("Result:",report["mode"],report["counts"],
          "submitted:",report["submitted"],
          "confirmed:",report["verified_after_write"])
    print("Other unresolved:",sorted(UNRESOLVED))
    return int(report["mode"] in (
        "apply_aborted_unexpected_existing_xrefs",
        "apply_interrupted_unexpected_xrefs",
        "apply_interrupted_uncertain",
        "apply_interrupted_unverified",
    ))

if __name__=="__main__":
    raise SystemExit(main())
