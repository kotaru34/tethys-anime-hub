import httpx
from app.config import settings
from app.media import is_real_item


class JellyfinClient:
    def __init__(self, http=None):
        config = settings()
        if not config.jellyfin_url or not config.jellyfin_api_key:
            raise RuntimeError('JELLYFIN_URL / JELLYFIN_API_KEY not configured')
        self.base = config.jellyfin_url.rstrip('/')
        self.http = http or httpx.Client(timeout=35, headers={'X-Emby-Token': config.jellyfin_api_key})

    def fetch_items(self, kinds: str):
        items = []
        offset = 0
        while True:
            response = self.http.get(self.base + '/Items', params={
                'Recursive': 'true', 'IncludeItemTypes': kinds,
                'Fields': 'ProviderIds,MediaSources,Path,Overview,PremiereDate,ProductionYear',
                'StartIndex': offset, 'Limit': 200,
            })
            response.raise_for_status()
            payload = response.json()
            batch = payload.get('Items') or []
            items.extend(batch)
            offset += len(batch)
            if not batch or offset >= payload.get('TotalRecordCount', offset):
                return items

    def catalog(self):
        """Avoid an extra disk scan: consume the library already indexed by Shoko/Shokofin."""
        shows = self.fetch_items('Series,Movie')
        episodes = self.fetch_items('Episode')
        children = {}
        for ep in episodes:
            if is_real_item(ep) and ep.get('SeriesId'):
                children.setdefault(ep['SeriesId'], []).append(ep)
        for item in shows:
            if item.get('Type') == 'Movie' and is_real_item(item):
                children.setdefault(item['Id'], []).append(item)
        return shows, children

    def image(self, item_id: str):
        r = self.http.get(self.base + f'/Items/{item_id}/Images/Primary', params={'width': 420, 'quality': 85})
        if r.status_code == 404:
            return None
        r.raise_for_status()
        mime = r.headers.get('content-type', 'image/jpeg')
        if not mime.startswith('image/') or len(r.content) > 4_000_000:
            return None
        return r.content, mime
