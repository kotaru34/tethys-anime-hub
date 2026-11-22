#!/usr/bin/env python3
"""Close four verified promotional videos by setting Shoko IsIgnored=true.

This changes ONLY Shoko's per-file ignored flag. Physical MKVs and their
torrent-seeding paths are never accessed. No deletion, relink, scan, or rehash.

python3 ignore_final_four_pvs.py --apply --confirm IGNORE_FOUR_PVS \
  --report /root/shoko-final-four-pv-ignore.json

Without --apply, perform a read-only preflight. The apply mode includes the
same preflight and requires all four exact IDs, RelativePaths, and empty XRefs.
"""
from __future__ import annotations

import argparse
from collections import Counter
from contextlib import nullcontext
import os
from pathlib import Path
import time

from shoko_reconcile import ShokoAPI
from resolve_45_onepass import build_expected
from targeted_metadata_bootstrap import atomic_json, exclusive_state_lock

PVS = {
    2994: "KonoSuba S1 PV",
    2997: "KonoSuba S2 PV2",
    2999: "KonoSuba S2 PV1",
    3020: "High School DxD BorN PV",
}
ALL_PATHS,_ = build_expected()
PATHS = {fid:ALL_PATHS[fid] for fid in PVS}
STATE = Path("/var/lib/shoko-reconcile/final-four-pv-ignore-20261122.state.json")


def read_journal(path=STATE):
    if not path.exists():
        return {"schema":1,"attempts":{}}
    import json
    data = json.loads(path.read_text(encoding="utf-8"))
    if (not isinstance(data,dict) or data.get("schema") != 1
        or not isinstance(data.get("attempts"),dict)
        or not set(data["attempts"]).issubset({str(fid) for fid in PVS})):
        raise ValueError("Invalid final-four ignore journal")
    return data


def get_file(api, fid):
    data = api.request("GET",f"/File/{fid}",{"include":"XRefs"})
    if not isinstance(data,dict) or data.get("ID") != fid:
        raise ValueError(f"Invalid file details for {fid}")
    if PATHS[fid] not in {
        loc.get("RelativePath") for loc in data.get("Locations") or []
        if isinstance(loc,dict)
    }:
        raise ValueError(f"Exact RelativePath changed for {fid}; no writes")
    if type(data.get("IsIgnored")) is not bool:
        raise ValueError(f"Missing IsIgnored flag for {fid}")
    # Shoko 5.3.3's File model has SeriesIDs but NO
    # MetadataCrossReferences property. This optional field was introduced
    # later for non-AniDB release links. In 5.3.3, its absence is normal.
    # Still fail closed if required AniDB XRefs are absent or either
    # supplied field is malformed (not a list).
    if not isinstance(data.get("SeriesIDs"), list):
        raise ValueError(f"File {fid}: missing AniDB SeriesIDs from include=XRefs")
    if ("MetadataCrossReferences" in data and
            not isinstance(data["MetadataCrossReferences"], list)):
        raise ValueError(f"File {fid}: invalid MetadataCrossReferences payload")
    data.setdefault("MetadataCrossReferences", [])
    return data


def unknown_page(api):
    response = api.request("GET","/File",{
        "include_only":"Unrecognized","pageSize":100,"page":1})
    if (not isinstance(response,dict)
        or type(response.get("Total")) is not int
        or not isinstance(response.get("List"),list)
        or response["Total"] > 100
        or response["Total"] != len(response["List"])):
        raise ValueError("Invalid/truncated unrecognized page")
    ids = []
    for item in response["List"]:
        fid = item.get("ID")
        if type(fid) is not int or fid < 1 or fid in ids:
            raise ValueError("Invalid or duplicate unrecognized File ID")
        ids.append(fid)
    return set(ids),response["Total"]


def preflight(api,journal):
    unknown,total = unknown_page(api)
    rows={}
    for fid,label in sorted(PVS.items()):
        file = get_file(api,fid)
        refs = file["SeriesIDs"]
        other_refs = file["MetadataCrossReferences"]
        row = {
            "file_id":fid,"label":label,"path":PATHS[fid],
            "ignored_before":file["IsIgnored"],
            "xrefs_count":sum(len(series.get("EpisodeIDs") or [])
                              for series in refs),
            "metadata_refs_count":len(other_refs),
        }
        if refs or other_refs:
            row.update(status="blocked",
                       reason="file_has_existing_episode_or_release_links")
        elif file["IsIgnored"]:
            row["status"]="already_ignored"
        elif fid not in unknown:
            row.update(status="blocked",
                       reason="file_is_not_unrecognized_and_not_ignored")
        elif str(fid) in journal["attempts"]:
            attempt=journal["attempts"][str(fid)]
            if not isinstance(attempt,dict) or attempt.get("path") != PATHS[fid]:
                row.update(status="blocked",reason="journal_path_mismatch")
            else:
                row["status"]="previous_attempt_unverified_no_repeat"
        else:
            row["status"]="ready"
        rows[fid]=row
    return {
        "mode":"dry_run","unrecognized_before":total,
        "unknown_ids_before":sorted(unknown),
        "rows":rows,
        "submitted":0,"verified":0,
    }


def poll_flag(api,fid,*,sleep=time.sleep,clock=time.monotonic,seconds=3):
    deadline=clock()+seconds
    while True:
        try:
            data=get_file(api,fid)
            if data["IsIgnored"] and not data["SeriesIDs"] and not data["MetadataCrossReferences"]:
                return "verified"
            if data["SeriesIDs"] or data["MetadataCrossReferences"]:
                return "conflict"
        except Exception:
            pass
        if clock() >= deadline:
            return "pending"
        sleep(min(0.5,max(0,deadline-clock())))


def apply_batch(api,journal,persist,*,sleep=time.sleep,
                clock=time.monotonic,verify_wait=3):
    report=preflight(api,journal)
    report["mode"]="apply"
    if any(row["status"]=="blocked" for row in report["rows"].values()):
        report["mode"]="apply_aborted_preflight"
        return finish(api,report)
    for fid in sorted(PVS):
        row=report["rows"][fid]
        if row["status"] in ("already_ignored",):
            continue
        if row["status"]=="previous_attempt_unverified_no_repeat":
            result=poll_flag(api,fid,sleep=sleep,clock=clock,seconds=verify_wait)
            row["status"]=(
                "prior_attempt_now_verified" if result=="verified" else
                "previous_attempt_conflict" if result=="conflict" else
                "prior_attempt_still_unverified_no_repeat")
            if result=="conflict":
                report["mode"]="apply_interrupted_conflict"
                break
            continue
        if row["status"]!="ready":
            continue
        # Just-in-time check against Shoko automatic recognition/other edits.
        latest=get_file(api,fid)
        if latest["IsIgnored"] and not latest["SeriesIDs"] and not latest["MetadataCrossReferences"]:
            row["status"]="already_ignored_during_run"
            continue
        if latest["IsIgnored"] or latest["SeriesIDs"] or latest["MetadataCrossReferences"]:
            row.update(status="blocked",reason="file_changed_since_preflight")
            report["mode"]="apply_interrupted_conflict"
            break
        unknown,_=unknown_page(api)
        if fid not in unknown:
            row.update(status="blocked",reason="no_longer_unrecognized_at_write")
            report["mode"]="apply_interrupted_conflict"
            break
        journal["attempts"][str(fid)]={
            "path":PATHS[fid],"at":int(time.time()),"operation":"ignore_true",
            "status":"dispatch_uncertain"}
        persist(journal)
        try:
            api.request("PUT",f"/File/{fid}/Ignore",{"value":"true"})
        except Exception as exc:
            journal["attempts"][str(fid)]["status"]="request_error_uncertain"
            persist(journal)
            row.update(status="request_error_uncertain",
                       error=f"{type(exc).__name__}: {str(exc)[:180]}")
            report["mode"]="apply_interrupted_uncertain"
            break
        report["submitted"]+=1
        result=poll_flag(api,fid,sleep=sleep,clock=clock,seconds=verify_wait)
        journal["attempts"][str(fid)]["status"]=result
        persist(journal)
        if result=="verified":
            row["status"]="ignored_verified"
            report["verified"]+=1
        elif result=="pending":
            row["status"]="submitted_pending_no_repeat"
        else:
            row["status"]="unexpected_xref_after_ignore"
            report["mode"]="apply_interrupted_conflict"
            break
    return finish(api,report)


def finish(api,report):
    # Only a bounded read. Explicitly distinguish "zero" from stale/new files.
    pending=any(row["status"] in (
        "submitted_pending_no_repeat",
        "prior_attempt_still_unverified_no_repeat",
        "request_error_uncertain") for row in report["rows"].values())
    try:
        unknown,count=unknown_page(api)
        report["unrecognized_after"]=count
        report["unknown_ids_after"]=sorted(unknown)
    except Exception as exc:
        report["unrecognized_check_error"]=f"{type(exc).__name__}: {str(exc)[:180]}"
    report["counts"]=dict(Counter(row["status"] for row in report["rows"].values()))
    if report["mode"]=="apply" and pending:
        report["mode"]="apply_pending_verification"
    report["scope"]={
        "exact_file_ids":sorted(PVS),"max_unrecognized_page_size":100,
        "shoko_writes_only":"PUT /File/{fileID}/Ignore?value=true",
        "file_deletes":0,"media_writes":0,"torrent_changes":0,
        "reshashes":0,"library_scans":0,"background_tasks":0,
    }
    return report


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--url",default="http://127.0.0.1:8111")
    p.add_argument("--state",type=Path,default=STATE)
    p.add_argument("--report",type=Path,
                   default=Path("/root/shoko-final-four-pv-ignore.json"))
    p.add_argument("--apply",action="store_true")
    p.add_argument("--confirm",default="")
    p.add_argument("--verify-wait",type=int,default=3)
    a=p.parse_args(argv)
    if a.apply and a.confirm!="IGNORE_FOUR_PVS":
        p.error("Use --confirm IGNORE_FOUR_PVS")
    if not 0 <= a.verify_wait <= 30:
        p.error("--verify-wait must be within 0..30 seconds")
    if not os.getenv("SHOKO_API_KEY"):
        p.error("Export SHOKO_API_KEY first")
    context=exclusive_state_lock(a.state) if a.apply else nullcontext()
    try:
        with context:
            journal=read_journal(a.state)
            api=ShokoAPI(a.url,os.environ["SHOKO_API_KEY"])
            report=(apply_batch(api,journal,
                                 lambda value:atomic_json(a.state,value),
                                 verify_wait=a.verify_wait)
                    if a.apply else finish(api,preflight(api,journal)))
            atomic_json(a.report,report)
    except BlockingIOError:
        p.error("Another final-four ignore command holds the lock")
    print("Report:",a.report)
    print("Result:",report["mode"],report["counts"],
          "submitted:",report["submitted"],"verified:",report["verified"],
          "unrecognized after:",report.get("unrecognized_after","unknown"))
    return int(report["mode"] not in ("apply","dry_run"))


if __name__=="__main__":
    raise SystemExit(main())
