"""Single replica worker. Keeps expensive and network work out of request handlers."""
import logging
import sys
import time
from datetime import timedelta
from sqlalchemy import select
from app.config import settings
from app.db import Anime, Episode, SessionLocal, put_state, read_state, utcnow
from app.jellyfin import JellyfinClient
from app.media import provider_id, streams, release_group, summarize_episodes
from app.sources import AniListClient, mapping_for_anidb, choose_candidate
from app.subtitles import sync_subtitles

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(name)s: %(message)s')
log = logging.getLogger(__name__)


def sync_jellyfin(client=None):
    source = client or JellyfinClient()
    shows, children = source.catalog()  # successful complete fetch before changing DB
    now = utcnow()
    active, episode_ids = set(), set()
    with SessionLocal() as db:
        for item in shows:
            jid = str(item['Id'])
            active.add(jid)
            name = item.get('Name') or 'Unknown'
            row = db.get(Anime, jid)
            providers = item.get('ProviderIds') or {}
            if row is None:
                row = Anime(id=jid, title=name, source_title=name, overview=item.get('Overview'),
                            year=item.get('ProductionYear'), premiere=item.get('PremiereDate'),
                            match_status='unmatched', provider_ids=providers)
                db.add(row)
            else:
                row.source_title = name
                if not row.anilist_id:
                    row.title = name
                if not row.overview:
                    row.overview = item.get('Overview')
                row.year = item.get('ProductionYear') or row.year
                row.premiere = item.get('PremiereDate') or row.premiere
                row.provider_ids = providers
            row.available = bool(children.get(jid))
            row.anidb_id = provider_id(providers, 'AniDB', 'AniDB.Net', 'anidb')
            linked = provider_id(providers, 'AniList')
            if linked and row.match_status != 'manual' and row.anilist_id != linked:
                row.anilist_id = linked
                row.match_status = 'provider'
                row.enriched_at = None
            actual_episodes = children.get(jid, [])
            stats = summarize_episodes(actual_episodes)
            for field, value in stats.items():
                setattr(row, field, value)
            for ep in actual_episodes:
                eid = str(ep['Id'])
                episode_ids.add(eid)
                record = db.get(Episode, eid)
                if record is None:
                    record = Episode(id=eid, anime_id=jid)
                    db.add(record)
                a, s = streams(ep)
                record.anime_id = jid
                record.name = ep.get('Name') or ''
                record.season = ep.get('ParentIndexNumber')
                record.number = ep.get('IndexNumber')
                record.path = ep.get('Path')
                record.audio_languages = a
                record.subtitle_languages = s
                record.release_group = release_group(ep.get('Path'))
        for row in db.scalars(select(Anime)).all():
            if row.id not in active:
                row.available = False  # retain ratings/reviews forever
        for row in db.scalars(select(Episode)).all():
            if row.id not in episode_ids:
                db.delete(row)
        put_state(db, 'last_jellyfin_sync', now.isoformat())
        put_state(db, 'last_jellyfin_count', len(active))
        db.commit()
    log.info('Jellyfin indexed: %d titles; %d playable episodes/movies', len(active), len(episode_ids))
    return len(active)


def _find_match(row: Anime, client: AniListClient):
    if row.anilist_id:
        return
    if row.anidb_id:
        mapped = mapping_for_anidb(row.anidb_id, settings().state_dir)
        if mapped:
            row.anilist_id = mapped
            row.match_status = 'anidb-map'
            row.match_confidence = 1.0
            return
    candidate_id, status, score, candidates = choose_candidate(row.source_title or row.title, row.year, client)
    row.match_candidates = candidates
    row.match_status = status
    row.match_confidence = score
    if candidate_id:
        row.anilist_id = candidate_id


def _apply_detail(row: Anime, data: dict):
    titles = data.get('title') or {}
    row.title = titles.get('english') or titles.get('romaji') or row.source_title
    row.overview = data.get('description') or row.overview
    date = data.get('startDate') or {}
    if date.get('year'):
        row.year = date['year']
        row.premiere = '-'.join(str(date.get(part) or 1).zfill(2 if part != 'year' else 4)
                                for part in ('year', 'month', 'day'))
    row.total_episodes = data.get('episodes')
    row.cover_url = (data.get('coverImage') or {}).get('large')
    row.studios = sorted({n['name'] for n in ((data.get('studios') or {}).get('nodes') or [])
                          if n and n.get('name')})
    relations = []
    for edge in ((data.get('relations') or {}).get('edges') or []):
        other = edge.get('node') or {}
        if not other.get('id'):
            continue
        rel_titles = other.get('title') or {}
        relations.append({
            'id': other['id'], 'kind': edge.get('relationType'),
            'title': rel_titles.get('english') or rel_titles.get('romaji') or 'Untitled',
            'episodes': other.get('episodes'), 'format': other.get('format'),
            'cover_url': (other.get('coverImage') or {}).get('medium'),
        })
    row.relations = relations
    row.enriched_at = utcnow()


def enrich_batch(client=None, limit=30):
    api = client or AniListClient()
    now = utcnow()
    done = 0
    remaining = 0
    with SessionLocal() as db:
        titles = db.scalars(select(Anime).where(Anime.available.is_(True)).order_by(Anime.enriched_at.asc().nullsfirst())).all()
        for row in titles:
            fresh_for = timedelta(days=30 if row.anilist_id else 7)
            if row.enriched_at and now - row.enriched_at < fresh_for:
                continue
            if done >= limit:
                remaining += 1
                continue
            try:
                _find_match(row, api)
                if row.anilist_id:
                    detail = api.detail(row.anilist_id)
                    if detail is None:
                        row.anilist_id = None
                        row.match_status = 'needs_review'
                        row.enriched_at = utcnow()
                    else:
                        _apply_detail(row, detail)
                else:
                    row.enriched_at = utcnow()
                db.commit()
                done += 1
            except Exception:
                db.rollback()
                log.exception('Enrichment failed for Jellyfin ID %s', row.id)
                # Stop instead of hammering API during service outages.
                break
        put_state(db, 'last_enrichment', utcnow().isoformat())
        db.commit()
    log.info('Enriched %d; pending %d', done, remaining)
    return done, remaining


def main(once=False):
    cfg = settings()
    last_sync = last_enrich = last_subs = 0.0
    while True:
        now = time.monotonic()
        try:
            with SessionLocal() as db:
                requested = read_state(db, 'sync_requested', '0') == '1'
                if requested:
                    put_state(db, 'sync_requested', '0')
                    db.commit()
            if requested:
                last_enrich = 0.0  # immediately refresh manual AniList overrides
            if requested or now - last_sync >= cfg.sync_interval_seconds:
                sync_jellyfin()
                last_sync = time.monotonic()
            if now - last_enrich >= cfg.enrich_interval_seconds:
                count, pending = enrich_batch()
                last_enrich = time.monotonic() - (cfg.enrich_interval_seconds - 10 if pending else 0)
            if now - last_subs >= cfg.subtitle_interval_seconds:
                with SessionLocal() as db:
                    scanned = sync_subtitles(db, '/Anime')
                    put_state(db, 'sidecar_count', scanned)
                    put_state(db, 'last_sidecar_sync', utcnow().isoformat())
                    db.commit()
                log.info('Nested subtitle files indexed: %d', scanned)
                last_subs = time.monotonic()
            with SessionLocal() as db:
                put_state(db, 'last_error', '')
                db.commit()
        except Exception as exc:
            log.exception('Worker cycle failed')
            with SessionLocal() as db:
                put_state(db, 'last_error', type(exc).__name__ + ': ' + str(exc)[:500])
                db.commit()
        if once:
            return
        time.sleep(15)


if __name__ == '__main__':
    main(once='--once' in sys.argv)
