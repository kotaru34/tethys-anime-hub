"""Closed set of external metadata sources: AniList and Fribb anime-lists."""
import json
import logging
import os
import time
from pathlib import Path
from difflib import SequenceMatcher
from functools import lru_cache
from urllib.parse import urlparse
import httpx
from app.config import settings
from app.media import clean_query

log = logging.getLogger(__name__)
ANILIST = 'https://graphql.anilist.co'
MAPPING = 'https://raw.githubusercontent.com/Fribb/anime-lists/master/anime-list-full.json'

DETAIL_QUERY = '''
query ($id: Int) {
  Media(id: $id, type: ANIME) {
    id title { romaji english native } synonyms episodes format status
    seasonYear startDate { year month day }
    coverImage { large medium }
    description(asHtml: false)
    studios(isMain: true) { nodes { name isAnimationStudio } }
    relations { edges { relationType node {
      id title { romaji english native } episodes format coverImage { medium }
    } } }
  }
}
'''
SEARCH_QUERY = '''
query ($query: String) {
  Page(perPage: 10) { media(search: $query, type: ANIME) {
    id title { romaji english native } synonyms seasonYear episodes format
  } }
}
'''


class AniListClient:
    def __init__(self, http=None):
        self.client = http or httpx.Client(timeout=22.0, headers={'User-Agent': 'kotaru-anime-private/0.1'})
        self.last_query = 0.0

    def graphql(self, query, variables):
        # The public endpoint has been operating at a degraded 30/min limit.
        spacing = max(0.0, 2.5 - (time.monotonic() - self.last_query))
        if spacing:
            time.sleep(spacing)
        for attempt in range(3):
            self.last_query = time.monotonic()
            r = self.client.post(ANILIST, json={'query': query, 'variables': variables})
            if r.status_code == 429:
                delay = min(90, max(3, int(r.headers.get('Retry-After', '60'))))
                log.warning('AniList rate limited: sleeping %ss', delay)
                time.sleep(delay)
                continue
            r.raise_for_status()
            payload = r.json()
            if payload.get('errors'):
                raise RuntimeError(f'AniList error: {payload["errors"][0].get("message", "unknown")}')
            return payload['data']
        raise RuntimeError('AniList rate limit retries exhausted')

    def detail(self, anime_id: int):
        return self.graphql(DETAIL_QUERY, {'id': anime_id}).get('Media')

    def search(self, title: str):
        data = self.graphql(SEARCH_QUERY, {'query': clean_query(title)})
        return (data.get('Page') or {}).get('media') or []


def mapping_for_anidb(anidb_id: int, state_dir: str, http=None) -> int | None:
    """Bounded, local AniDB→AniList map. Refresh weekly, keep old cache on failures."""
    directory = Path(state_dir)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / 'anime-list-full.json'
    if not path.exists() or time.time() - path.stat().st_mtime > 7 * 86400:
        try:
            response = (http or httpx).get(MAPPING, timeout=40.0, follow_redirects=True)
            response.raise_for_status()
            if len(response.content) > 35 * 1024 * 1024:
                raise RuntimeError('Mapping unexpectedly large')
            parsed = response.json()
            if not isinstance(parsed, list) or len(parsed) < 1000:
                raise ValueError('Invalid mapping dataset')
            temp = path.with_suffix('.tmp')
            temp.write_bytes(response.content)
            os.replace(temp, path)
        except (OSError, ValueError, httpx.HTTPError, RuntimeError) as exc:
            log.warning('AniDB mapping refresh failed, using cached data if available: %s', exc)
    if not path.exists():
        return None
    try:
        return _read_mapping(str(path), path.stat().st_mtime_ns).get(anidb_id)
    except (OSError, ValueError, TypeError) as exc:
        log.warning('Invalid mapping cache: %s', exc)
        return None


@lru_cache(maxsize=3)
def _read_mapping(path: str, mtime_ns: int) -> dict[int, int]:
    data = json.loads(Path(path).read_text(encoding='utf-8'))
    return {int(entry['anidb_id']): int(entry['anilist_id'])
            for entry in data if entry.get('anidb_id') and entry.get('anilist_id')}


def title_key(s):
    import re
    return re.sub(r'[^a-z0-9]+', '', clean_query(s).casefold())


def score_candidate(title: str, anime: dict, year: int | None = None) -> float:
    title_info = anime.get('title') or {}
    names = [title_info.get('romaji'), title_info.get('english'), title_info.get('native')]
    names.extend(anime.get('synonyms') or [])
    key = title_key(title)
    ratios = [SequenceMatcher(None, key, title_key(name)).ratio()
              for name in names if name and title_key(name)]
    score = max(ratios, default=0.0)
    candidate_year = anime.get('seasonYear')
    if year and candidate_year and abs(year - candidate_year) > 2:
        score -= 0.13
    return round(max(0.0, score), 4)


def candidates_for(title: str, year, client: AniListClient):
    results = client.search(title)
    enriched = []
    for entry in results:
        enriched.append({
            'id': entry['id'],
            'title': (entry.get('title') or {}).get('english') or (entry.get('title') or {}).get('romaji') or 'Unknown',
            'year': entry.get('seasonYear'),
            'format': entry.get('format'),
            'score': score_candidate(title, entry, year),
        })
    return sorted(enriched, key=lambda x: x['score'], reverse=True)


def qwen_choice(title: str, candidates: list[dict]) -> int | None:
    cfg = settings()
    if not cfg.llm_enabled or not candidates:
        return None
    # No tools, filesystem, network browsing or database writes are exposed to the model.
    allowed_ids = {c['id'] for c in candidates}
    url = cfg.llm_base_url.rstrip('/') + '/chat/completions'
    prompt = (
        'Identify the anime corresponding to the original release/title. '
        'Choose exclusively from the candidate IDs. If uncertain return null. '
        'Output ONLY JSON: {"id": integer_or_null}.\n'
        f'Input title: {json.dumps(title, ensure_ascii=False)}\n'
        f'Candidates: {json.dumps(candidates, ensure_ascii=False)}'
    )
    headers = {'Authorization': f'Bearer {cfg.llm_api_key or "none"}'}
    try:
        with httpx.Client(timeout=55) as client:
            response = client.post(url, headers=headers, json={
                'model': cfg.llm_model, 'temperature': 0,
                'response_format': {'type': 'json_object'},
                'messages': [
                    {'role': 'system', 'content': 'You are a strict anime ID classifier. Never invent IDs. Return {"id": null} if uncertain.'},
                    {'role': 'user', 'content': prompt},
                ],
                'max_tokens': 90,
            })
            response.raise_for_status()
            message = response.json()['choices'][0]['message']['content']
            value = json.loads(message).get('id')
            return value if type(value) is int and value in allowed_ids else None
    except (httpx.HTTPError, ValueError, KeyError, IndexError) as exc:
        log.warning('LLM unavailable or non-JSON response: %s', exc)
        return None


def choose_candidate(title: str, year: int | None, client: AniListClient):
    candidates = candidates_for(title, year, client)
    if not candidates:
        return None, 'needs_review', None, []
    first = candidates[0]
    second = candidates[1]['score'] if len(candidates) > 1 else 0.0
    if first['score'] >= 0.94 and first['score'] - second >= 0.08:
        return first['id'], 'fuzzy', first['score'], candidates
    picked = qwen_choice(title, candidates)
    if picked is not None:
        selected = next(c for c in candidates if c['id'] == picked)
        # The LLM can resolve ambiguity but cannot override a strongly implausible match.
        if selected['score'] >= 0.68:
            return picked, 'llm', selected['score'], candidates
    return None, 'needs_review', None, candidates
