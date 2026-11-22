#!/usr/bin/env python3
"""One-file, read-only Akatsuki no Yona OVA (03+SP) episode-content probe.

No /File enumeration, no /Anime scan, no Shoko mutations, no MKV changes.
Verifies exact known File ID/path and the two distinct AniDB episodes.
Uses ffprobe to read the header and chapter/time data for JUST that file.

The existence of both AniDB episodes and a matching filename does NOT prove
the physical file contains both. Shoko's Manual Link "Duplicate Entry" virtual
file feature is only appropriate after the actual contents are confirmed.

  python3 yona_03_sp_probe.py --output /root/shoko-yona-03-sp-probe.json
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess

from shoko_reconcile import ShokoAPI
from targeted_metadata_bootstrap import atomic_json

FILE_ID = 2486
AID = 11143
SHOKO_SID = 270
RELATIVE_PATH = "Akatsuki no Yona OVA/Akatsuki no Yona OVA (03+SP).mkv"
TARGETS = (
    {"type": "Episode", "number": 3, "anidb_episode_id": 176847,
     "title": "The Yellow Dragon Zeno's Past, Part 2: The Red Star Rises"},
    {"type": "Special", "number": 1, "anidb_episode_id": 183623,
     "title": "Good Night for Today"},
)


def shoko_identity(api):
    """Three bounded targeted reads, no unrecognized-file enumeration."""
    result = {"file_id": FILE_ID, "relative_path": RELATIVE_PATH,
              "anidb_id": AID, "shoko_series_id": SHOKO_SID}
    file = api.request("GET", f"/File/{FILE_ID}")
    if not isinstance(file, dict) or file.get("ID") != FILE_ID:
        raise ValueError("Shoko File ID response unexpected")
    paths = [x.get("RelativePath") for x in file.get("Locations", [])
             if isinstance(x, dict)]
    if RELATIVE_PATH not in paths:
        raise ValueError("Shoko no longer associates File 2486 with exact reviewed path")
    result["file_path_verified"] = True
    # Shoko already has this file indexed. Its size and duration, when
    # supplied, remain useful even if the command-line user cannot stat or
    # read the bind-mounted file. Keep Shoko's raw duration value: the API
    # representation is not sufficient to establish seconds vs ticks.
    if type(file.get("Size")) is int:
        result["shoko_indexed_size_bytes"] = file["Size"]
    if isinstance(file.get("Duration"), (str, int, float)):
        result["shoko_indexed_duration_raw"] = file["Duration"]
    work = api.local_series(AID)
    ids = (work or {}).get("IDs") or {}
    if int(ids.get("ID") or 0) != SHOKO_SID or int(ids.get("AniDB") or 0) != AID:
        raise ValueError("Yona local AniDB work/series identity has changed")
    records = list(api.pages(f"/Series/{SHOKO_SID}/Episode", {
        "includeDataFrom": "AniDB", "includeMissing": "True",
        "includeUnaired": "True", "includeHidden": "True",
        "includeManuallyLinked": "True"}, size=500))
    if len(records) > 150:
        raise ValueError("Unexpectedly large targeted Yona episode inventory")
    found = []
    for target in TARGETS:
        matching = [e for e in records
                    if (e.get("AniDB") or {}).get("Type") == target["type"]
                    and (e.get("AniDB") or {}).get("EpisodeNumber") == target["number"]
                    and (e.get("AniDB") or {}).get("ID") == target["anidb_episode_id"]
                    and (e.get("AniDB") or {}).get("Title") == target["title"]]
        if len(matching) != 1:
            raise ValueError("Yona AniDB episode ID/type/number/title verification failed")
        found.append(dict(target))
    result["verified_episode_candidates"] = found
    return result


def probe_media(root: Path, *, ffprobe="ffprobe", run=subprocess.run):
    """Read one exact file (no decode/thumbnail writes), with command timeout."""
    # The Shoko service may have access to the same mount via another UID,
    # group, ACL or mount namespace. Path.is_file() raises PermissionError on
    # Python 3.13 when traversal/stat fails. Do not crash or rewrite ACLs.
    def inaccessible(stage, exc):
        return {
            "status": "media_access_denied" if isinstance(exc, PermissionError)
                      else "media_path_os_error",
            "stage": stage,
            "expected_path": str(path),
            "errno": exc.errno,
            "error": type(exc).__name__,
            "diagnostic": (
                "The current probe process cannot stat/traverse this path. "
                "Shoko indexing does not prove this process can access it. "
                "Check 'id' and 'namei -l' for the exact file and each parent; "
                "do not recursively chmod/chown the torrent library."),
        }

    try:
        root = root.resolve()
    except OSError as exc:
        path = root / RELATIVE_PATH
        return inaccessible("resolve_media_root", exc)
    path = root / RELATIVE_PATH
    try:
        if not root.is_dir():
            return {"status": "media_path_unavailable",
                    "expected_path": str(path),
                    "note": "The requested LXC media root is not a directory."}
    except OSError as exc:
        return inaccessible("stat_media_root", exc)
    try:
        if not path.is_file():
            return {"status": "media_path_unavailable",
                    "expected_path": str(path),
                    "note": "Shoko may know a path even when the LXC mount is unavailable."}
    except OSError as exc:
        return inaccessible("stat_media_file", exc)
    try:
        resolved_path = path.resolve()
    except OSError as exc:
        return inaccessible("resolve_media_file", exc)
    if not resolved_path.is_relative_to(root):
        raise ValueError("Symlink points outside requested read-only media root")
    binary = shutil.which(ffprobe) if ffprobe == "ffprobe" else ffprobe
    if binary is None:
        return {"status": "ffprobe_missing",
                "expected_path": str(path),
                "note": "Install ffprobe (ffmpeg package) in the LXC, no media file changes."}
    cmd = [binary, "-v", "error",
           "-show_entries",
           "format=duration,size,format_name:chapter=start_time,end_time:"
           "chapter_tags=title:stream=index,codec_type,codec_name:"
           "stream_tags=language,title",
           "-of", "json", str(path)]
    try:
        proc = run(cmd, capture_output=True, text=True,
                   errors="replace", timeout=90, check=False)
    except subprocess.TimeoutExpired:
        return {"status": "ffprobe_timeout",
                "expected_path": str(path)}
    except OSError as exc:
        return inaccessible("execute_ffprobe", exc)
    if proc.returncode != 0:
        return {"status": "ffprobe_error",
                "error": proc.stderr[:400] or "Unknown ffprobe error"}
    if len(proc.stdout) > 1_000_000:
        raise ValueError("ffprobe returned an unexpectedly large response")
    data = json.loads(proc.stdout)
    info = data.get("format") or {}
    try:
        duration = float(info.get("duration"))
    except (TypeError, ValueError):
        duration = None
    chapters = [{
        "start_time": x.get("start_time"),
        "end_time": x.get("end_time"),
        "title": (x.get("tags") or {}).get("title", "")[:160],
    } for x in (data.get("chapters") or [])[:100]]
    streams = [{
        "type": x.get("codec_type"),
        "codec": x.get("codec_name"),
        "language": (x.get("tags") or {}).get("language"),
        "title": str((x.get("tags") or {}).get("title") or "")[:160],
    } for x in (data.get("streams") or [])[:30]]
    return {"status": "probed",
            "path": str(path),
            "duration_seconds": duration,
            "duration_minutes": round(duration / 60, 2) if duration is not None else None,
            "size_bytes": int(info["size"]) if str(info.get("size") or "").isdigit() else None,
            "chapters": chapters,
            "streams": streams,
            "interpretation": (
                "Duration and chapters may indicate a combined OVA+special, but "
                "cannot prove which content is present. Watch the beginning and "
                "end before assigning E03 and S01 as two virtual episode links.")}


def inspect(api, root=Path("/Anime"), *, ffprobe="ffprobe", run=subprocess.run):
    identity = shoko_identity(api)
    return {
        "mode": "read_only_yona_combined_ova_probe",
        "shoko_identity": identity,
        "media": probe_media(root, ffprobe=ffprobe, run=run),
        "potential_links_if_content_verified": list(TARGETS),
        "safe_next_action": (
            "Verify the contents of the MKV directly; only if it really "
            "contains both E03 and Special S01, use Shoko's Manual Linking "
            "Duplicate Entry virtual file feature for the second episode. "
            "Do not link or split blindly."),
        "scope": {"targeted_file_gets": 1, "targeted_work_gets": 1,
                  "targeted_episode_lists": 1, "media_files_inspected": 1,
                  "full_file_scans": 0, "media_walks": 0, "xref_writes": 0,
                  "metadata_refresh_requests": 0},
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://127.0.0.1:8111")
    parser.add_argument("--anime-root", type=Path, default=Path("/Anime"))
    parser.add_argument("--output", type=Path, default=Path("/root/shoko-yona-03-sp-probe.json"))
    args = parser.parse_args(argv)
    key = os.getenv("SHOKO_API_KEY")
    if not key:
        parser.error("Set SHOKO_API_KEY in environment")
    report = inspect(ShokoAPI(args.url, key), root=args.anime_root)
    atomic_json(args.output, report)
    print(f"Report: {args.output}")
    print("Result:", report["mode"], "File ID:", FILE_ID,
          "media:", report["media"]["status"], "XRefs submitted: 0")


if __name__ == "__main__":
    main()
