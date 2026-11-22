#!/usr/bin/env python3
"""Close the two full-length numbered High School DxD OVAs only.

After the user's 45-file reconciliation, two numbered OVA files remain:
  File 3209: High School DxD OVA - 03  -> AniDB 11184 Episode E01 / ID 161394
  File 3206: High School DxD OVA - 04  -> AniDB 11844 Episode E01 / ID 167801

Independent published 1-4 OVA listings place the New OVA third and the
BorN OVA fourth. The ordinal evidence is strong but is NOT a frame-by-frame
content identity proof; the operator explicitly chooses to apply.

Four unrelated PVs have no proven AniDB Trailer targets. This script NEVER
links, ignores, renames or deletes those four files.

python3 link_final_dxd_two_ova.py --apply \
  --confirm LINK_CHRONOLOGICAL_DXD_OVAS_2 \
  --report /root/shoko-dxd-ova-closeout.json

No /Anime filesystem access and no global scans. Fail closed on any changed
path/work/episode/XRef. POST attempt journal persists before dispatch.
"""
from __future__ import annotations

import argparse
from collections import Counter
from contextlib import nullcontext
import os
from pathlib import Path
import time

from fix_dal_endings_final10 import current_refs
from resolve_45_onepass import build_expected
from shoko_reconcile import ShokoAPI
from targeted_metadata_bootstrap import atomic_json, exclusive_state_lock

STATE = Path("/var/lib/shoko-reconcile/final-dxd-ova-20261122.state.json")

# AniDB work ID, AniDB episode ID, AniDB episode type and number/title.
TARGETS = {
    3209: (11184, 161394, "Episode", 1, "OVA"),
    3206: (11844, 167801, "Episode", 1, "OVA"),
}
OTHER_PVS = {
    2994: "KonoSuba S1 promotional clip; no verified identical AniDB T entry",
    2999: "KonoSuba S2 PV1; no verified AniDB T entry",
    2997: "KonoSuba S2 PV2; no verified AniDB T entry",
    3020: "High School DxD BorN promotional clip; no verified AniDB T entry",
}
PATHS = {
    fid: path for fid,path in build_expected()[0].items() if fid in TARGETS
}
if set(PATHS) != set(TARGETS) or len(TARGETS) != 2:
    raise ValueError("Unexpected file identity allowlist")


def journal_read(path=STATE):
    if not path.exists():
        return {"schema":1, "attempts":{}}
    import json
    state = json.loads(path.read_text(encoding="utf-8"))
    if (not isinstance(state,dict) or state.get("schema") != 1
            or not isinstance(state.get("attempts"),dict)
            or not set(state["attempts"]).issubset(
                {str(fid) for fid in TARGETS})):
        raise ValueError("Invalid persistent attempt journal")
    return state


def strict_file(api, fid):
    value = api.request("GET",f"/File/{fid}",{"include":"XRefs"})
    if not isinstance(value,dict) or value.get("ID") != fid:
        raise ValueError(f"Missing/unexpected file ID {fid}")
    if not isinstance(value.get("SeriesIDs"),list):
        raise ValueError(f"XRefs not included for file {fid}")
    if PATHS[fid] not in {
        loc.get("RelativePath") for loc in value.get("Locations") or []
        if isinstance(loc,dict)
    }:
        raise ValueError(f"Exact relative path changed for file {fid}")
    return value


def unknown(api):
    response = api.request("GET","/File",{
        "include_only":"Unrecognized","pageSize":100,"page":1})
    if (not isinstance(response,dict)
        or type(response.get("Total")) is not int
        or response["Total"] > 100
        or not isinstance(response.get("List"),list)
        or response["Total"] != len(response["List"])):
        raise ValueError("Invalid or incomplete bounded Shoko Unrecognized listing")
    ids = set()
    for file in response["List"]:
        fid = file.get("ID")
        if type(fid) is not int or fid in ids:
            raise ValueError("Duplicate/invalid File ID in Unrecognized")
        ids.add(fid)
    return ids,response["Total"]


def validate_episode(api,aid,eid,kind,number,title):
    source = api.local_series(aid)
    ids = (source or {}).get("IDs") or {}
    sid = ids.get("ID")
    if (type(sid) is not int or sid < 1
        or ids.get("AniDB") != aid):
        return None, "local_anidb_work_missing_or_changed"
    records = list(api.pages(f"/Series/{sid}/Episode",{
        "includeDataFrom":"AniDB","includeMissing":"True",
        "includeUnaired":"True","includeHidden":"True",
        "includeManuallyLinked":"True"},size=500))
    if len(records) > 240:
        raise ValueError("Unexpected episode inventory size")
    episodes = []
    for row in records:
        ep = row.get("AniDB") or {}
        k = str(ep.get("Type") or "").casefold()
        k = "Episode" if k in ("episode","normal") else (
            "Special" if k in ("special","ova","ona") else k.title())
        n = ep.get("EpisodeNumber")
        if k == kind and n == number:
            episodes.append(ep)
    if len(episodes) != 1:
        return None, "episode_missing_or_ambiguous"
    ep = episodes[0]
    if ep.get("ID") != eid or ep.get("Title") != title:
        return None, "exact_anidb_episode_id_or_title_changed"
    return sid,None


def inspect(api,state):
    pending,total=unknown(api)
    rows={}
    for fid in sorted(TARGETS):
        aid,eid,kind,n,title=TARGETS[fid]
        file = strict_file(api,fid)
        refs = current_refs(file)
        sid,error = validate_episode(api,aid,eid,kind,n,title)
        row = {
            "file_id":fid,"relative_path":PATHS[fid],
            "target":{"anidb_work":aid,"shoko_series":sid,
                      "anidb_episode_id":eid,"type":kind,
                      "episode":n,"title":title},
            "observed_xrefs":refs,
        }
        if error:
            row.update(status="blocked",reason=error)
        elif refs == [(aid,eid)]:
            row["status"]="already_correct"
        elif refs:
            row.update(status="blocked",reason="unexpected_existing_episode_xref")
        elif str(fid) in state["attempts"]:
            attempt=state["attempts"][str(fid)]
            if (not isinstance(attempt,dict)
                or attempt.get("aid") != aid or attempt.get("eid") != eid):
                row.update(status="blocked",reason="previous_attempt_journal_mismatch")
            else:
                row["status"]="previous_attempt_unverified_no_retry"
        elif fid not in pending:
            row.update(status="blocked",reason="file_not_unrecognized_despite_zero_xrefs")
        else:
            row["status"]="ready"
        rows[fid]=row
    return {"mode":"dry_run","total_unrecognized_start":total,
            "rows":rows,"unchanged_pv_ids":sorted(OTHER_PVS),
            "pv_reason_by_file":OTHER_PVS}


def observe(api,fid,expected,sleep=time.sleep,clock=time.monotonic,seconds=3):
    deadline=clock()+seconds
    last=None
    while True:
        try:
            last=current_refs(strict_file(api,fid))
        except Exception as e:
            last=f"{type(e).__name__}: {str(e)[:180]}"
        if last == [expected]:return "verified",last
        if isinstance(last,list) and last:
            return "conflict",last
        if clock()>=deadline:return "pending",last
        sleep(min(1,max(0,deadline-clock())))


def apply(api,state,persist,*,sleep=time.sleep,clock=time.monotonic,verify_wait=3):
    report=inspect(api,state)
    report["mode"]="apply"
    report["submitted"]=0
    report["verified_after_post"]=0
    if any(r["status"]=="blocked" for r in report["rows"].values()):
        report["mode"]="apply_aborted_preflight"
        return summarize(report)
    for fid in sorted(TARGETS):
        r=report["rows"][fid]
        if r["status"]=="previous_attempt_unverified_no_retry":
            aid,eid,_,_,_=TARGETS[fid]
            result,seen=observe(api,fid,(aid,eid),sleep,clock,verify_wait)
            r["last_observed_xrefs"]=seen
            if result=="verified":
                r["status"]="prior_attempt_now_verified"
            elif result=="conflict":
                r.update(status="blocked",reason="unexpected_xref_after_previous_post")
                report["mode"]="apply_interrupted_conflict"
                return summarize(report)
        if r["status"]!="ready":
            continue
        aid,eid,kind,n,_=TARGETS[fid]
        latest=current_refs(strict_file(api,fid))
        if latest==[(aid,eid)]:
            r["status"]="already_correct_during_run"
            continue
        if latest:
            r.update(status="blocked",reason="xref_changed_after_preflight")
            report["mode"]="apply_interrupted_conflict"
            break
        # Since preflight can be stale, never write a formerly ignored file.
        current_unknown,_=unknown(api)
        if fid not in current_unknown:
            r.update(status="blocked",reason="unrecognized_state_changed")
            report["mode"]="apply_interrupted_conflict"
            break
        state["attempts"][str(fid)]={
            "aid":aid,"eid":eid,"at":int(time.time()),
            "outcome":"dispatch_uncertain"}
        persist(state)
        try:
            api.link(fid,r["target"]["shoko_series"],n,kind)
        except Exception as exc:
            state["attempts"][str(fid)]["outcome"]="network_error_uncertain"
            persist(state)
            r.update(status="request_error_uncertain",
                     reason=f"{type(exc).__name__}: {str(exc)[:180]}")
            report["mode"]="apply_interrupted_uncertain"
            break
        report["submitted"]+=1
        result,seen=observe(api,fid,(aid,eid),sleep,clock,verify_wait)
        r["last_observed_xrefs"]=seen
        if result=="verified":
            r["status"]="xref_verified"
            report["verified_after_post"]+=1
            state["attempts"][str(fid)]["outcome"]="verified"
        elif result=="pending":
            r["status"]="submitted_pending_no_retry"
            state["attempts"][str(fid)]["outcome"]="unverified_pending"
        else:
            r.update(status="blocked",reason="unexpected_xref_after_post")
            state["attempts"][str(fid)]["outcome"]="conflict_after_post"
            report["mode"]="apply_interrupted_conflict"
            persist(state)
            break
        persist(state)
    if report["mode"]=="apply":
        for fid in sorted(TARGETS):
            r=report["rows"][fid]
            if r["status"] not in (
                "previous_attempt_unverified_no_retry",
                "submitted_pending_no_retry"):
                continue
            aid,eid,_,_,_=TARGETS[fid]
            try:refs=current_refs(strict_file(api,fid))
            except Exception as exc:
                r["final_verify_error"]=f"{type(exc).__name__}: {str(exc)[:180]}"
                continue
            r["final_xrefs"]=refs
            if refs==[(aid,eid)]:
                r["status"]="prior_or_pending_now_verified"
                state["attempts"][str(fid)]["outcome"]="verified_final"
                persist(state)
            elif refs:
                r.update(status="blocked",reason="unexpected_nonempty_final_xref")
                report["mode"]="apply_interrupted_conflict"
                break
        if report["mode"]=="apply" and any(
            r["status"] in ("previous_attempt_unverified_no_retry",
                            "submitted_pending_no_retry")
            for r in report["rows"].values()):
            report["mode"]="apply_pending_confirmation"
    return summarize(report)


def summarize(report):
    report["counts"]=dict(Counter(r["status"] for r in report["rows"].values()))
    report["scope"]={
        "max_pinned_ova_file_ids":2,
        "unrecognized_list_page_limit":100,
        "shoko_work_read_scope":[11184,11844],
        "pv_ignored_or_linked":0,
        "filesystem_media_reads":0,
        "media_writes":0,"library_rescan":0,"background_tasks":0}
    return report


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--url",default="http://127.0.0.1:8111")
    p.add_argument("--state",type=Path,default=STATE)
    p.add_argument("--report",type=Path,default=Path("/root/shoko-dxd-ova-closeout.json"))
    p.add_argument("--apply",action="store_true")
    p.add_argument("--confirm",default="")
    p.add_argument("--verify-wait",type=int,default=3)
    a=p.parse_args(argv)
    if a.apply and a.confirm!="LINK_CHRONOLOGICAL_DXD_OVAS_2":
        p.error("Use --confirm LINK_CHRONOLOGICAL_DXD_OVAS_2")
    if not 0<=a.verify_wait<=60:
        p.error("--verify-wait requires 0..60")
    key=os.getenv("SHOKO_API_KEY")
    if not key:p.error("Set SHOKO_API_KEY")
    context=exclusive_state_lock(a.state) if a.apply else nullcontext()
    try:
        with context:
            state=journal_read(a.state)
            api=ShokoAPI(a.url,key)
            report=(apply(api,state,lambda obj:atomic_json(a.state,obj),
                          verify_wait=a.verify_wait)
                    if a.apply else summarize(inspect(api,state)))
            atomic_json(a.report,report)
    except BlockingIOError:
        p.error("Other closeout process holds the exclusive journal lock")
    print("Report:",a.report)
    print("Result:",report["mode"],report["counts"],
          "submitted:",report.get("submitted",0),
          "verified after POST:",report.get("verified_after_post",0))
    print("PV clips intentionally untouched:",sorted(OTHER_PVS))
    return int(report["mode"] in (
        "apply_aborted_preflight","apply_interrupted_conflict",
        "apply_interrupted_uncertain","apply_pending_confirmation"))


if __name__=="__main__":
    raise SystemExit(main())
