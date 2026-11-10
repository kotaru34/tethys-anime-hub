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


def episode_totals(items: list[dict], target: str | None = None):
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


def summarize_episodes(items: list[dict], target: str | None = None):
    audio, subs, groups = set(), set(), set()
    for item in items:
        a, s = streams(item)
        audio.update(a)
        subs.update(s)
        group = release_group(item.get('Path'))
        if group:
            groups.add(group)
    result = {
        'file_count': episode_totals(items)[0],
        'audio_languages': sorted(audio),
        'subtitle_languages': sorted(subs),
        'release_groups': sorted(groups),
    }
    # Legacy compatibility only: no globally chosen dubbing language.
    if target:
        result['dubbed_count'] = episode_totals(items, target)[1]
    return result


def is_real_item(item: dict) -> bool:
    return item.get('LocationType') != 'Virtual' and not item.get('IsMissingEpisode', False)


def clean_query(title: str):
    # Keep season numbers and other identifying information.
    title = re.sub(r'^\[[^\]]{2,90}\]\s*', '', title)
    title = re.sub(r'\b(1080p|720p|2160p|x264|x265|HEVC|AV1|Blu.?Ray|WEB.?DL|AAC|FLAC)\b', '', title, flags=re.I)
    return re.sub(r'\s+', ' ', title).strip(' -_[]()')

def episode_audio_counts(episodes) -> dict[str, int]:
    """Count distinct available episodes per actual audio language.

    Episode identity is (season, number), or a stable ID where that is unknown.
    Series specials are excluded if regular episodes exist, as in episode_totals.
    Missing/unknown language stays `und`, never assumed to be any locale.
    """
    regular = [ep for ep in episodes if ep.season != 0]
    countable = regular if regular else list(episodes)
    per_episode = {}
    for ep in countable:
        identity = (ep.season, ep.number) if ep.season is not None or ep.number is not None else ('id', ep.id)
        languages = per_episode.setdefault(identity, set())
        for lang in (ep.audio_languages or []):
            languages.add(str(lang).lower().strip() or 'und')
    result = defaultdict(int)
    for languages in per_episode.values():
        for lang in languages:
            result[lang] += 1
    return dict(sorted(result.items()))
