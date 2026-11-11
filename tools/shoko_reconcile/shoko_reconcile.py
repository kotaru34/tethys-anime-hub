#!/usr/bin/env python3
"""Tethys Shoko 5.3.3 reconciler v2: evidence-based release/episode linking.

No writes to /Anime, MKV, original Shoko DB, or AniDB. Shoko REST manual links
only after explicit --apply --confirm LINK. Supports offline revision of v1 reports.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
import json
import os
from pathlib import Path, PurePosixPath
import sys
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from matching import (EpisodeInfo, classify_episode, clean_release_title,
    main_title_candidates, rank_candidates, choose_candidate, similarity, season_hint, match_key)
from catalog import AliasCatalog

class ShokoAPI:
    def __init__(self, base: str, key: str, timeout: float = 20):
        if not base.startswith(("http://127.0.0.1:", "http://localhost:", "https://")):
            raise ValueError("Use localhost or an HTTPS Shoko URL; do not send API keys over remote HTTP")
        self.base = base.rstrip("/") + "/api/v3"
        self.key = key
        self.timeout = timeout

    def request(self, method: str, path: str, params: dict | None = None, body: dict | None = None):
        url = self.base + path + (("?" + urlencode(params)) if params else "")
        data = None if body is None else json.dumps(body).encode("utf-8")
        headers = {"apikey": self.key, "Accept": "application/json"}
        if data is not None:
            headers["Content-Type"] = "application/json"
        req = Request(url, data=data, headers=headers, method=method)
        try:
            with urlopen(req, timeout=self.timeout) as response:
                payload = response.read()
                return json.loads(payload) if payload else None
        except HTTPError as ex:
            detail = ex.read(500).decode("utf-8", "replace")
            raise RuntimeError(f"Shoko API {method} {path} -> {ex.code}: {detail}") from ex
        except URLError as ex:
            raise RuntimeError(f"Shoko API unavailable: {ex.reason}") from ex

    def pages(self, path: str, params: dict | None = None, size=500):
        page = 1
        while True:
            r = self.request("GET", path, {**(params or {}), "pageSize": size, "page": page})
            if not isinstance(r, dict) or not isinstance(r.get("List"), list):
                raise RuntimeError(f"Unexpected Shoko API ListResult for {path}")
            yield from r["List"]
            if page * size >= r.get("Total", len(r["List"])) or not r["List"]:
                break
            page += 1

    def unrecognized(self):
        return list(self.pages("/File", {"include_only": "Unrecognized"}))

    def anime_search(self, title: str):
        return list(self.pages("/Series/AniDB/Search", {"query": title, "fuzzy": "true",
                       "includeTitles": "true", "searchById": "false"}, size=100))[:100]

    def local_series(self, anidb_id: int):
        # Shoko may already know the series by AniDB ID, even if no local media is linked.
        try:
            return self.request("GET", f"/Series/AniDB/{anidb_id}/Series")
        except RuntimeError as e:
            if "-> 404:" in str(e):
                return None
            raise

    def refresh_series(self, anidb_id: int):
        return self.request("POST", f"/Series/AniDB/{anidb_id}/Refresh",
                            {"createSeriesEntry": "true", "downloadRelations": "false", "force": "false"})

    def available_episodes(self, series_id: int) -> set[tuple[str, int]]:
        """Verify actual AniDB episode type and number exist in Shoko before linking."""
        records = self.pages(f"/Series/{series_id}/Episode", {
            "includeDataFrom": "AniDB", "includeMissing": "True", "includeUnaired": "True",
            "includeHidden": "True", "includeManuallyLinked": "True"})
        result = set()
        for record in records:
            source = record.get("AniDB") or {}
            kind = str(source.get("Type", "")).casefold()
            number = source.get("EpisodeNumber")
            if kind in ("episode", "normal"): kind = "Episode"
            elif kind in ("special", "ova", "ona"): kind = "Special"
            elif kind in ("credits", "trailer", "parody", "other"): kind = kind.title()
            else: continue
            if isinstance(number, int) and number > 0: result.add((kind, number))
        return result

    def link(self, file_id: int, series_id: int, episode: int, kind="Episode"):
        # Shoko 5.3.3 ModelHelper parses S/C/T/P/O/E prefixes; no dummy file hash.
        prefix = {"Episode":"", "Movie":"", "Special":"S", "Credits":"C",
                  "Trailer":"T", "Parody":"P", "Other":"O"}.get(kind)
        if prefix is None: raise ValueError(f"Unsupported episode type: {kind}")
        target = f"{prefix}{episode}"
        return self.request("POST", f"/File/{file_id}/LinkFromSeries", body={
            "SeriesID": series_id, "RangeStart": target, "RangeEnd": target})

    def metadata(self, series_id: int):
        series = self.request("GET", f"/Series/{series_id}", {"includeDataFrom":"AniDB,TMDB"})
        episodes = list(self.pages(f"/Series/{series_id}/Episode", {
            "includeDataFrom":"AniDB,TMDB", "includeMissing":"True",
            "includeUnaired":"True", "includeHidden":"True", "includeManuallyLinked":"True",
            "includeFiles":"True", "includeMediaInfo":"True", "includeXRefs":"True"}, size=500))
        return {"shoko_series_id": series_id, "series": series, "episodes": episodes}


def group_unrecognized(files: list[dict]) -> dict[str, list[dict]]:
    groups = defaultdict(list)
    for f in files:
        locations = f.get("Locations") or []
        relative = (locations[0].get("RelativePath") or "").replace("\\", "/") if locations else ""
        parts = PurePosixPath(relative).parts
        folder = parts[0] if len(parts) > 1 else "__missing_folder__"
        groups[folder].append(f)
    return dict(groups)


def _group_from_raw(folder, media):
    return {"folder": folder,
            "files": [{"file_id": int(f["ID"]),
                       "path": (f.get("Locations") or [{}])[0].get("RelativePath") or ""}
                      for f in media]}


def _selected_anchor(group, ranked):
    """v1 exact-title was based on Shoko title aliases omitted from its JSON candidate rows.

    Retain such evidence only when that same candidate is present in original results;
    semantic type/episode checks still run at file level.
    """
    aid = group.get("selected_anidb_id")
    if aid and group.get("mode") == "exact_title" and any(
            int(c["anidb_id"]) == int(aid) for c in group.get("candidates", [])):
        return int(aid)
    return None


def analyze_report(source: dict, *, catalog=None, overrides=None, aggressive=False) -> dict:
    """Use existing Shoko v1 discovery results; DOES NOT query or change Shoko."""
    if source.get("version") not in (1, 2): raise ValueError("Unknown source report version")
    overrides = overrides or {}
    group_overrides = overrides.get("groups", overrides) if isinstance(overrides, dict) else {}
    file_overrides = overrides.get("files", {}) if isinstance(overrides, dict) else {}
    # Reuse independent AniDB title candidates seen in *other* release groups.
    # A sequel missing from one Shoko fuzzy search is often present in its prequel's hits.
    global_pool = {}
    for other in source["groups"]:
        for candidate in other.get("candidates", []):
            aid = candidate.get("anidb_id")
            if aid and candidate.get("title"):
                global_pool[int(aid)] = candidate
    out = {"version":2, "source_total_files_at_scan": source.get("total_files_at_scan",source.get("source_total_files_at_scan")), "source_unrecognized_at_scan": source.get("total_unrecognized_at_scan",source.get("source_unrecognized_at_scan")),
           "groups":[], "mode":"offline_reanalysis", "catalog_used":bool(catalog)}
    for original in source["groups"]:
        folder=original["folder"]
        files=original.get("files") or []
        guesses=main_title_candidates(folder, files)
        candidates=[]
        for c in original.get("candidates",[]):
            candidates.append({"anidb_id":c.get("anidb_id"),"title":c.get("title"),
                               "shoko_id":c.get("shoko_id"),"type":c.get("type","Unknown"),
                               "source":c.get("source", "v1_shoko_search"),
                               "Titles":c.get("Titles",[]),"aliases":c.get("aliases",[]),
                               "year":c.get("year"),"episodes":c.get("episodes")})
        own_ids={int(c["anidb_id"]) for c in candidates if c.get("anidb_id")}
        for aid,c in global_pool.items():
            if aid in own_ids:continue
            if any(similarity(q,c.get("title") or "") > 0.64 for q in guesses):
                candidates.append({"anidb_id":aid,"title":c["title"],"type":c.get("type","Unknown"),
                                   "source":"cross_group_shoko_candidate"})
        if catalog:
            for query in guesses:
                candidates.extend(catalog.lookup(query))
        parsed=[classify_episode(f["path"],group=folder) for f in files]
        ranked=rank_candidates(guesses,candidates,folder=folder)
        selected,mode,reason=choose_candidate(ranked,folder=folder,parsed=parsed,
                                              min_score=0.79 if aggressive else 0.85)
        anchor=_selected_anchor(original,ranked)
        if anchor is not None and not ("OVA" in folder.upper() and len(files)>2):
            selected,mode,reason=anchor,"prior_exact_title","Shoko exact title/alias match in original scan"
        if folder in group_overrides:
            requested=int(group_overrides[folder])
            selected=requested if requested>0 else None
            mode="approved_override" if requested>0 else "review"
            reason="explicit user release override" if requested>0 else "explicit user skip"
        # The original data lacks per-file provenance of distinct titles or variants.
        # Require same episodic series within group; flag unrelated stems as conflict.
        rows=[]
        top_cand=next((c for c in ranked if c["anidb_id"]==selected),None)
        for f,ep in zip(files,parsed):
            fid=int(f["file_id"])
            kind=ep.category; number=ep.number
            aid=selected; local_mode=mode; note=ep.reason
            # Movies may have no numeric marker; a single main movie is episode 1.
            if kind=="Unknown" and aid and top_cand and top_cand.get("type"," ").casefold()=="movie":
                if not any("/" in x["path"].split(folder+"/",1)[-1] for x in [f]) and                         not any(q in f["path"].lower() for q in ("bonus/","extra/","specials/")):
                    kind="Movie";number=1;note="un-numbered feature film (candidate metadata confirms Movie)"
            # Full group with a secondary distinctly named anime/spin-off is not a single work.
            stem=PurePosixPath(f["path"]).stem
            if "youjo shenki" in stem.casefold() and "youjo senki" in folder.casefold():
                aid=None;local_mode="review";note="distinct spin-off title: Youjo Shenki"
            if kind=="Extra":
                aid=None;local_mode="extra";number=None
            if kind=="Unknown" or number is None:
                aid=None
                if local_mode not in ("extra","review"):local_mode="episode_review"
            file_ov = file_overrides.get(str(fid)) if isinstance(file_overrides,dict) else None
            if file_ov:
                aid=int(file_ov.get("anidb_id") or 0) or None
                number=int(file_ov.get("episode") or 0) or None
                kind=str(file_ov.get("type") or kind)
                local_mode="approved_file_override" if aid and number else "review"
                note="explicit user file-level override"
            rows.append({"file_id":fid,"path":f["path"],"source_episode":f.get("episode"),
                         "episode":number,"episode_type":kind,"target_anidb_id":aid,
                         "mode":local_mode,"reason":note})
        out["groups"].append({"folder":folder,"title_guess":clean_release_title(folder),
            "queries":guesses,"selected_anidb_id":selected,"mode":mode,"reason":reason,
            "candidates":ranked,"count":len(rows),"files":rows})
    from refinements import refine
    return refine(out, catalog=catalog)


def prepare(api: ShokoAPI, overrides: dict, catalog=None, aggressive=False):
    files=api.unrecognized()
    raw={"version":1,"total_files_at_scan":sum(1 for _ in api.pages("/File")),
         "total_unrecognized_at_scan":len(files),"groups":[]}
    search_cache={}
    for folder,media in sorted(group_unrecognized(files).items()):
        group=_group_from_raw(folder,media)
        guesses=main_title_candidates(folder,group["files"])
        results={}
        for query in guesses[:3]:
            if query not in search_cache:
                search_cache[query]=api.anime_search(query) if query and not folder.startswith("__") else []
            for c in search_cache[query]:
                if c.get("ID"):results[int(c["ID"])]=c
        # Preserve full AniDB search result Titles, rather than v1's stripped candidate names.
        group.update({"candidates": [{"anidb_id":r["ID"],"title":r.get("Title"),
                        "type":r.get("Type","Unknown"),"shoko_id":r.get("ShokoID"),
                        "Titles":r.get("Titles",[])} for r in results.values()],
                      "mode":"review","selected_anidb_id":None})
        raw["groups"].append(group)
    return analyze_report(raw,catalog=catalog,overrides=overrides,aggressive=aggressive)


def metrics(plan):
    total=sum(len(g.get("files",[])) for g in plan["groups"])
    potential=sum(1 for g in plan["groups"] for f in g["files"]
                  if f.get("target_anidb_id") and f.get("episode")
                  and f["mode"] not in ("review","episode_review","extra"))
    extras=sum(1 for g in plan["groups"] for f in g["files"] if f.get("mode")=="extra")
    all_files=plan.get("source_total_files_at_scan")
    remaining=total-potential
    target=int(all_files*0.05) if all_files else None
    return {"total_unrecognized_in_plan":total,"potential_links_before_api_validation":potential,
        "deferred":remaining,"extras_not_counted_as_recognized":extras,
        "projected_unknown_percent_if_all_submitted_links_succeed":
            round(100*remaining/all_files,2) if all_files else None,
        "max_unknown_files_for_5pct_target":target,
        "additional_verified_links_needed_after_this_plan":
            max(0,remaining-target) if target is not None else None}


def _series_id_from_api(value):
    if not isinstance(value,dict):return None
    ids=value.get("IDs") or {}
    result=ids.get("ID") or value.get("ID")
    return int(result) if result else None


def apply(api: ShokoAPI, plan, *, delay=0.2, limit=None, journal=None):
    if plan.get("version")!=2:raise ValueError("Only version-2 plans may be applied")
    if limit is not None and limit<1:raise ValueError("Limit must be positive")
    current={int(f["ID"]):f for f in api.unrecognized()}
    done=failed=deferred=pending=0
    series_cache={};episodes_cache={}
    audit=[]
    should_stop=False
    for group in plan["groups"]:
        for row in group["files"]:
            if limit is not None and done+failed+pending>=limit:
                should_stop=True;break
            aid=row.get("target_anidb_id")
            ep=row.get("episode")
            if row.get("mode") in ("review","episode_review","extra") or not aid or not ep:
                deferred+=1;continue
            fid=int(row["file_id"])
            source=current.get(fid)
            if not source:
                deferred+=1;continue
            paths={l.get("RelativePath") for l in source.get("Locations") or []}
            if row.get("path") not in paths:
                deferred+=1;print(f"SKIP stale file {fid}",file=sys.stderr);continue
            aid=int(aid)
            if aid not in series_cache:
                series=api.local_series(aid)
                sid=_series_id_from_api(series)
                if sid:
                    actual=(series.get("IDs") or {}).get("AniDB")
                    if actual is None or int(actual)!=aid:
                        raise RuntimeError(f"Shoko series identity mismatch for AniDB {aid}")
                else:
                    api.refresh_series(aid)
                series_cache[aid]=sid
            sid=series_cache[aid]
            if not sid:
                pending+=1;continue
            if sid not in episodes_cache:
                episodes_cache[sid]=api.available_episodes(sid)
            kind=str(row.get("episode_type") or "Episode")
            actual_kind = "Episode" if kind=="Movie" else kind
            available=episodes_cache[sid]
            if isinstance(available,set) and all(isinstance(a,int) for a in available):
                exists=(actual_kind=="Episode" and int(ep) in available)
            else:exists=(actual_kind,int(ep)) in available
            if not exists:
                deferred+=1;continue
            try:
                api.link(fid,sid,int(ep),kind)
                done+=1
                audit.append({"file_id":fid,"anidb_id":aid,"shoko_series_id":sid,
                              "episode":ep,"type":kind,"result":"submitted"})
                print(f"SUBMITTED file={fid} AniDB={aid} series={sid} {kind}={ep}")
            except Exception as ex:
                failed+=1;print(f"ERROR file={fid}: {ex}",file=sys.stderr)
                audit.append({"file_id":fid,"anidb_id":aid,"episode":ep,"type":kind,
                              "result":"error","message":str(ex)[:240]})
            if journal:
                _write_private_json(journal,{"version":1,"attempts":audit})
            if delay:time.sleep(delay)
        if should_stop:break
    return {"submitted":done,"errors":failed,"awaiting_series_refresh":pending,
            "deferred":deferred,"audit":audit}


def _write_private_json(path,obj):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    tmp=path.with_suffix(path.suffix+".tmp")
    with tmp.open("w",encoding="utf8") as fh:json.dump(obj,fh,indent=2,ensure_ascii=False)
    os.chmod(tmp,0o600)
    os.replace(tmp,path)


def export_metadata(api, plan, dest):
    """Persist actual per-episode AniDB/TMDB records from Shoko, separate from MKVs."""
    out=Path(dest);out.mkdir(mode=0o700,parents=True,exist_ok=True)
    aids=sorted({int(f["target_anidb_id"]) for g in plan["groups"] for f in g["files"]
                 if f.get("target_anidb_id")})
    count=0
    for aid in aids:
        s=api.local_series(aid)
        sid=_series_id_from_api(s)
        if sid:
            doc=api.metadata(sid)
            doc.update({"anidb_id":aid,"provenance":"Shoko API v3: AniDB/TMDB episode metadata",
                        "has_verified_anidb_file_id":False})
            _write_private_json(out/f"anidb-{aid}.json",doc)
            count+=1
    return {"series_snapshots":count,"destination":str(out),"episode_data":"included in each series JSON"}


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url",default=os.getenv("SHOKO_URL","http://127.0.0.1:8111"))
    parser.add_argument("--plan",default="shoko-plan-v2.json")
    parser.add_argument("--analyze-plan",help="OFFLINE: read a previous v1/v2 plan and upgrade its matching")
    parser.add_argument("--total-files",type=int,help="Full Shoko file count for offline target calculations")
    parser.add_argument("--catalog",help="Optional local anime-offline-database.jsonl crosswalk file")
    parser.add_argument("--overrides",help="User-approved JSON {groups:{folder:anidb_id},files:{file_id:{anidb_id,episode,type}}}")
    parser.add_argument("--aggressive",action="store_true",help="Use broader title candidate threshold (auditable; not guaranteed 90%% accurate)")
    parser.add_argument("--status",action="store_true")
    parser.add_argument("--apply",action="store_true")
    parser.add_argument("--confirm",help="Must be LINK for writes")
    parser.add_argument("--limit",type=int,help="Limit eligible files attempted, including waiting-for-refresh files")
    parser.add_argument("--journal",help="Path to private write-attempt audit log")
    parser.add_argument("--export-metadata",metavar="DIR",help="Save actual per-episode AniDB/TMDB data locally; no MKV writes")
    args=parser.parse_args(argv)
    if args.analyze_plan and (args.apply or args.status or args.export_metadata):parser.error("--analyze-plan is offline only")
    catalog=AliasCatalog(args.catalog) if args.catalog else None
    overrides={}
    if args.overrides:
        with open(args.overrides,encoding="utf8") as fh:overrides=json.load(fh)
    if args.analyze_plan:
        with open(args.analyze_plan,encoding="utf8") as fh:source=json.load(fh)
        if args.total_files:
            if args.total_files<1:parser.error("--total-files must be positive")
            source["total_files_at_scan"]=args.total_files
        if source.get("version") == 2 and not overrides:
            # v2 plans already contain file-level evidence and user decisions.
            # Rebuilding from their top-10 display candidates would discard data.
            from refinements import refine
            report = refine(source, catalog=catalog)
        else:
            report=analyze_report(source,catalog=catalog,overrides=overrides,aggressive=args.aggressive)
        _write_private_json(args.plan,report)
        print(json.dumps(report["metrics"],indent=2))
        print(f"Offline reanalysis written: {args.plan}; no Shoko changes")
        return
    key=os.getenv("SHOKO_API_KEY","")
    if not key:parser.error("SHOKO_API_KEY not set (only offline analysis runs without it)")
    api=ShokoAPI(args.url,key)
    if args.status:
        total=sum(1 for _ in api.pages("/File"))
        unknown=len(api.unrecognized())
        print(json.dumps({"total_files":total,"unrecognized":unknown,
            "unknown_percent":round(100*unknown/total,2) if total else None,
            "meets_5_percent_target":bool(total and unknown/total<=0.05)},indent=2))
        return
    if args.apply:
        if args.confirm!="LINK":parser.error("--apply requires --confirm LINK")
        with open(args.plan,encoding="utf8") as fh:report=json.load(fh)
        result=apply(api,report,limit=args.limit,journal=args.journal)
        print(json.dumps({k:v for k,v in result.items() if k!="audit"},indent=2))
        return
    if args.export_metadata:
        with open(args.plan,encoding="utf8") as fh:report=json.load(fh)
        print(json.dumps(export_metadata(api,report,args.export_metadata),indent=2))
        return
    report=prepare(api,overrides,catalog=catalog,aggressive=args.aggressive)
    _write_private_json(args.plan,report)
    print(json.dumps(report["metrics"],indent=2))
    print(f"Plan written: {args.plan}; no Shoko changes. Apply only after checking candidates.")

if __name__=="__main__":main()
