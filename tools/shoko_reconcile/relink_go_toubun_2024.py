#!/usr/bin/env python3
"""Safely correct the two verified 2024 Go-Toubun files in Shoko.

Manual links are replaced by Shoko's own LinkFromSeries API, not by deleting
the file or editing the torrent. Default is strict read-only preflight.
Release evidence:
  https://anilibria.tv/release/5-toubun-no-hanayome-specials2.html
"""
import argparse
import json
import os
from shoko_reconcile import ShokoAPI, _series_id_from_api

OLD_AID = 17968   # 2023 specials
NEW_AID = 18603   # 2024 specials
FIXES = [(778, 1), (779, 2)]
EXPECTED_RELEASE = "Go-Toubun no Hanayome~ - AniLibria.TV"


def inspect(api):
    series = api.local_series(NEW_AID)
    sid = _series_id_from_api(series)
    if not sid or int((series.get("IDs") or {}).get("AniDB") or -1) != NEW_AID:
        raise RuntimeError("2024 AniDB 18603 is not loaded in Shoko; refresh it first")
    episodes = api.available_episodes(sid)
    checks = []
    for fid, number in FIXES:
        file = api.request("GET", f"/File/{fid}", {"include": "XRefs"})
        if file.get("ID") != fid:
            raise RuntimeError(f"Unexpected File ID for {fid}")
        locs = file.get("Locations") or []
        paths = [str(loc.get("RelativePath") or "") for loc in locs]
        if not any(path.startswith(EXPECTED_RELEASE + " [") and
                   "/" in path and
                   (f"[{number:02d}]" in path.split("/", 1)[1])
                   for path in paths):
            raise RuntimeError(f"File {fid} has changed path; refusing to touch it")
        refs = file.get("SeriesIDs") or []
        ids = {int((ref.get("SeriesID") or {}).get("AniDB") or -1) for ref in refs}
        if ids == {NEW_AID}:
            checks.append({"file_id": fid, "episode": number, "status": "already_correct"})
            continue
        if ids != {OLD_AID}:
            raise RuntimeError(f"File {fid} is not exclusively linked to AniDB {OLD_AID}: {sorted(ids)}")
        if any(ep.get("Source") == "AniDB"
               for ref in refs for ep in ref.get("EpisodeIDs") or []):
            raise RuntimeError(f"File {fid} has a native AniDB link; manual correction forbidden")
        if ("Episode", number) not in episodes:
            raise RuntimeError(f"2024 Shoko series lacks episode {number}")
        checks.append({"file_id": fid, "episode": number, "status": "ready"})
    return sid, checks


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default=os.getenv("SHOKO_URL", "http://127.0.0.1:8111"))
    parser.add_argument("--refresh", action="store_true", help="Request new 2024 series metadata")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--confirm", default="")
    args = parser.parse_args()
    if args.apply and args.confirm != "RELINK":
        parser.error("--apply requires --confirm RELINK")
    key = os.getenv("SHOKO_API_KEY")
    if not key:
        parser.error("SHOKO_API_KEY must be configured")
    api = ShokoAPI(args.url, key)
    if args.refresh:
        api.refresh_series(NEW_AID)
        print("Metadata refresh requested for AniDB 18603. Wait for Shoko jobs, then run preflight.")
        return
    sid, checks = inspect(api)
    print(json.dumps({"2024_shoko_series_id": sid, "checks": checks}, indent=2))
    if args.apply:
        for row in checks:
            if row["status"] != "ready":
                continue
            # Shoko validates the target episode and replaces old non-AniDB refs.
            api.link(row["file_id"], sid, row["episode"], "Episode")
            print(f"Submitted File {row['file_id']} -> AniDB 18603 E{row['episode']:02}")
        print("Check completion in Shoko; submissions are queued jobs, not finished links.")


if __name__ == "__main__":
    main()
