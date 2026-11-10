"""Deterministic extraction of metadata from Jellyfin items and filenames."""
import re
from collections import defaultdict


def provider_id(providers: dict | None, *keys: str) -> int | None:
    data = {str(k).lower(): v for k, v in (providers or {}).items()}
    for key in keys:
        raw = data.get(key.lower())
        if raw is None:
            continue
        try:
            number = int(raw)
            if number > 0:
                return number
        except (TypeError, ValueError):
            pass
    return None


def release_group(path: str | None) -> str | None:
    # Avoid guessing from non-group folder names.
    if not path:
        return None
    filename = path.replace('\\', '/').split('/')[-1]
    match = re.match(r'^\[([^\]]{2,90})\]', filename)
    if match:
        return match.group(1).strip()
    match = re.search(r'\s-\s\[([^\]]{2,90})\](?:\.|$)', filename)
    return match.group(1).strip() if match else None


def streams(item: dict) -> tuple[list[str], list[str]]:
    audio, subtitles = set(), set()
    sources = item.get('MediaSources') or []
    for source in sources:
        for stream in source.get('MediaStreams') or []:
            typ = str(stream.get('Type') or '').lower()
            lang = (stream.get('Language') or 'und').lower().strip()
            if typ == 'audio':
                audio.add(lang)
            elif typ == 'subtitle':
                subtitles.add(lang)
    return sorted(audio), sorted(subtitles)


def episode_totals(items: list[dict], target: str):
    """Deduplicate episode identities, not source file count; movie counts as 1."""
    # A Jellyfin Season 0 special should not inflate a TV season count.
    standard = [i for i in items if i.get('ParentIndexNumber') != 0]
    countable = standard if standard else items
    uniq: dict[tuple, dict] = {}
    for item in countable:
        key = (item.get('ParentIndexNumber'), item.get('IndexNumber'))
        if key == (None, None):
            key = ('id', item['Id'])
        audio, _ = streams(item)
        old = uniq.get(key)
        if old is None:
            uniq[key] = {'dubbed': target in audio}
        else:
            old['dubbed'] |= target in audio
    return len(uniq), sum(1 for value in uniq.values() if value['dubbed'])


def summarize_episodes(items: list[dict], target: str):
    audio, subs, groups = set(), set(), set()
    for item in items:
        a, s = streams(item)
        audio.update(a)
        subs.update(s)
        group = release_group(item.get('Path'))
        if group:
            groups.add(group)
    return {
        'file_count': episode_totals(items, target)[0],
        'dubbed_count': episode_totals(items, target)[1],
        'audio_languages': sorted(audio),
        'subtitle_languages': sorted(subs),
        'release_groups': sorted(groups),
    }


def is_real_item(item: dict) -> bool:
    return item.get('LocationType') != 'Virtual' and not item.get('IsMissingEpisode', False)


def clean_query(title: str):
    # Keep season numbers and other identifying information.
    title = re.sub(r'^\[[^\]]{2,90}\]\s*', '', title)
    title = re.sub(r'\b(1080p|720p|2160p|x264|x265|HEVC|AV1|Blu.?Ray|WEB.?DL|AAC|FLAC)\b', '', title, flags=re.I)
    return re.sub(r'\s+', ' ', title).strip(' -_[]()')
