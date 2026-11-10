"""Read-only external subtitle inventory. Does NOT modify Shokofin-managed VFS."""
import os
import re
from pathlib import Path
from app.db import Sidecar, utcnow
import pycountry

EXTENSIONS = {'.ass', '.ssa', '.srt', '.vtt', '.sub', '.idx', '.sup'}
# Recognize the ISO 639 codes exposed by pycountry, not a favorite-language list.
# This is only a filename hint: unknown language is preserved, not guessed.
LANGS = frozenset(
    str(code).lower() for language in pycountry.languages
    for name in ('alpha_2', 'alpha_3', 'bibliographic', 'terminology')
    if (code := getattr(language, name, None))
)
EP_PATTERN = re.compile(r'(?:^|[\s._\[(-])(?:e|ep|episode)?\s*0?(\d{1,3})(?:v\d)?(?:[\s._\])\-]|$)', re.I)


def subtitle_hint(filename: str):
    name = Path(filename).stem.casefold()
    tokens = [v for v in re.split(r'[^a-z0-9]+', name) if v]
    lang = next((v for v in reversed(tokens) if v in LANGS), None)
    match = EP_PATTERN.search(name)
    number = int(match.group(1)) if match else None
    return lang, number


def inventory(root: str):
    """Only /Anime/release/*.mkv and nested subtitle directories are relevant."""
    base = Path(root)
    if not base.is_dir():
        raise FileNotFoundError(f'Media root not found: {root}')
    for release in base.iterdir():
        if not release.is_dir() or release.is_symlink():
            continue
        if not any(f.is_file() and f.suffix.lower() == '.mkv' for f in release.iterdir()):
            continue
        for directory, subdirs, files in os.walk(release, followlinks=False):
            if directory == str(release):
                continue  # user only requested subtitles in nested folders
            subdirs[:] = [s for s in subdirs if not Path(directory, s).is_symlink()]
            for name in files:
                p = Path(directory) / name
                if p.suffix.lower() in EXTENSIONS and not p.is_symlink():
                    lang, number = subtitle_hint(name)
                    yield {
                        'relative_path': p.relative_to(base).as_posix(),
                        'release': release.name,
                        'language_hint': lang,
                        'episode_hint': number,
                        'extension': p.suffix.lower(),
                    }


def sync_subtitles(db, root: str):
    seen = set()
    now = utcnow()
    for data in inventory(root):
        key = data['relative_path']
        seen.add(key)
        row = db.get(Sidecar, key)
        if row is None:
            db.add(Sidecar(**data, seen_at=now))
        else:
            for k, v in data.items():
                setattr(row, k, v)
            row.seen_at = now
    # Remove records for files that no longer exist only after a successful inventory.
    from sqlalchemy import select
    for row in db.scalars(select(Sidecar)).all():
        if row.relative_path not in seen:
            db.delete(row)
    db.commit()
    return len(seen)
