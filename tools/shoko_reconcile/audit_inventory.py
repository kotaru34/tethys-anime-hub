#!/usr/bin/env python3
"""Read-only audit of media on Shoko import-folder mounts versus Shoko's file index.

On CT2601 (with SHOKO_API_KEY exported):
    python3 audit_inventory.py
    runuser -u shoko -- env SHOKO_API_KEY="$SHOKO_API_KEY" python3 audit_inventory.py

No scan scheduling, no file hashing, no writes to Shoko, /Anime, or torrent state.
Run as the actual Shoko Server OS user to test its filesystem visibility.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import os
from pathlib import Path, PurePosixPath
import sys

from shoko_reconcile import ShokoAPI

MEDIA_EXTENSIONS = frozenset({".mkv", ".mp4", ".avi", ".webm", ".m4v", ".mov", ".ts", ".mpg", ".mpeg"})


def normalize_relative(path):
    """Normalize API location strings without hiding traversal or absolute paths."""
    value = str(path or "").replace("\\", "/")
    value = value.removeprefix("./")
    pure = PurePosixPath(value)
    if not value or pure.is_absolute() or ".." in pure.parts:
        return None
    return pure.as_posix()


def disk_inventory(root, extensions=MEDIA_EXTENSIONS):
    """Return {relative_path: bytes} and all directory/stat/open errors."""
    entries = {}
    errors = []
    if not root.is_dir():
        errors.append(f"{root}: not a directory or not accessible")
        return entries, errors

    def onerror(error):
        errors.append(f"{getattr(error, 'filename', '?')}: {error}")

    for directory, _subdirs, files in os.walk(root, followlinks=False, onerror=onerror):
        for name in files:
            path = Path(directory) / name
            if path.suffix.casefold() not in extensions:
                continue
            rel = path.relative_to(root).as_posix()
            try:
                # stat() alone is insufficient to detect unreadable media for
                # the Shoko service user: an unreadable MKV can still be listed.
                with path.open("rb"):
                    size = path.stat().st_size
                entries[rel] = size
            except OSError as ex:
                errors.append(f"{path}: {ex}")
    return entries, errors


def indexed_inventory(api):
    """Return (import_folders, indexed relative-path sizes per ImportFolder ID)."""
    folders = api.request("GET", "/ImportFolder")
    if not isinstance(folders, list):
        raise ValueError("Unexpected Shoko /ImportFolder response")
    indexed = defaultdict(dict)
    total_files = 0
    for f in api.pages("/File"):
        total_files += 1
        size = int(f.get("Size") or 0)
        for loc in f.get("Locations") or []:
            if loc.get("ImportFolderID") is None:
                continue
            rel = normalize_relative(loc.get("RelativePath"))
            if rel is not None:
                indexed[int(loc["ImportFolderID"])][rel] = size
    return folders, indexed, total_files


def differences(disk, indexed):
    """Compare exact relative names. Shoko includes inaccessible/stale DB records."""
    missing = {rel: size for rel, size in disk.items() if rel not in indexed}
    stale = {rel: size for rel, size in indexed.items() if rel not in disk}
    size_mismatch = {
        rel: (size, indexed[rel])
        for rel, size in disk.items()
        if rel in indexed and size != indexed[rel]
    }
    return missing, stale, size_mismatch


def mib(n):
    return f"{n / (1024 ** 2):,.1f} MiB"


def show_samples(title, paths, max_lines):
    if not paths:
        return
    print(f"  {title}:")
    for path, size in sorted(paths.items(), key=lambda p: (-p[1], p[0]))[:max_lines]:
        print(f"    {mib(size):>13}  {path}")
    if len(paths) > max_lines:
        print(f"    ... {len(paths) - max_lines} additional entries")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default=os.getenv("SHOKO_URL", "http://127.0.0.1:8111"))
    parser.add_argument("--max-lines", type=int, default=60)
    parser.add_argument("--only-folder", type=int, help="Limit to an import folder ID")
    args = parser.parse_args(argv)

    key = os.environ.get("SHOKO_API_KEY")
    if not key:
        parser.error("SHOKO_API_KEY is missing")
    api = ShokoAPI(args.url, key)
    folders, indexed, total_files = indexed_inventory(api)
    print(f"Shoko API indexed File records: {total_files}")
    print(f"Process UID={os.geteuid()} GID={os.getegid()} (match Shoko Server for permission testing)")
    any_missing = False
    any_errors = False
    for folder in folders:
        folder_id = int(folder["ID"])
        if args.only_folder is not None and args.only_folder != folder_id:
            continue
        root = Path(folder["Path"])
        disk, errors = disk_inventory(root)
        registered = {
            path: size for path, size in indexed[folder_id].items()
            if Path(path).suffix.casefold() in MEDIA_EXTENSIONS
        }
        missing, stale, mismatched = differences(disk, registered)
        any_missing |= bool(missing)
        any_errors |= bool(errors)
        print(f"\nImportFolder {folder_id}: {folder.get('Name', '<unnamed>')} ({root})")
        print(f"  On disk (video): {len(disk)} files, {mib(sum(disk.values()))}")
        print(f"  In Shoko index:  {len(registered)} file locations, {mib(sum(registered.values()))}")
        print(f"  On disk, absent in Shoko: {len(missing)} files, {mib(sum(missing.values()))}")
        print(f"  Indexed, absent from readable disk walk: {len(stale)} files, {mib(sum(stale.values()))}")
        print(f"  Size mismatches: {len(mismatched)}; filesystem errors: {len(errors)}")
        show_samples("UNINDEXED MEDIA", missing, args.max_lines)
        show_samples("STALE INDEX LOCATIONS (or inaccessible)", stale, args.max_lines)
        if mismatched:
            print("  SIZE MISMATCH (disk -> Shoko):")
            for rel, (actual, expected) in list(mismatched.items())[:args.max_lines]:
                print(f"    {rel}: {mib(actual)} -> {mib(expected)}")
        if errors:
            print("  FILESYSTEM ERRORS:")
            for error in errors[:args.max_lines]:
                print(f"    {error}")
            if len(errors) > args.max_lines:
                print(f"    ... {len(errors)-args.max_lines} additional errors")
        if missing:
            groups = Counter()
            for path, size in missing.items():
                top_dir = PurePosixPath(path).parts[0]
                groups[top_dir] += size
            print("  UNINDEXED BY RELEASE FOLDER:")
            for name, total in groups.most_common(args.max_lines):
                print(f"    {mib(total):>13}  {name}")
    if any_errors:
        print("\nWARNING: filesystem visibility is incomplete; cannot treat 'unindexed' as exhaustive.")
        return 2
    if any_missing:
        print("\nWARNING: readable media on disk missing from Shoko's index.")
        return 1
    print("\nNo unindexed readable video files found in examined import folders.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
