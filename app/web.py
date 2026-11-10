"""Minimal authenticated server-rendered catalog and REST endpoints."""
import os
import secrets
import logging
from functools import lru_cache
from urllib.parse import quote
import httpx
from fastapi import FastAPI, Request, Depends, Form, HTTPException, Query
from fastapi.responses import HTMLResponse, RedirectResponse, Response, JSONResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from sqlalchemy import select, or_, func, text
from sqlalchemy.orm import Session
from starlette.middleware.sessions import SessionMiddleware
from app.config import settings
from app.db import Anime, Episode, Sidecar, SessionLocal, get_db, put_state, read_state
from app.jellyfin import JellyfinClient
from app.media import episode_audio_counts

log = logging.getLogger(__name__)
cfg = settings()
if not cfg.app_password or not cfg.session_secret or len(cfg.session_secret) < 32:
    raise RuntimeError('Set APP_PASSWORD and SESSION_SECRET (>=32 characters) in .env')

app = FastAPI(title='Tethys Anime Hub', docs_url=None, redoc_url=None, openapi_url=None)
app.add_middleware(SessionMiddleware, secret_key=cfg.session_secret, session_cookie='tethys_session',
                   same_site='lax', https_only=os.getenv('COOKIE_SECURE', '0') == '1', max_age=60*60*24*14)
BASE = os.path.dirname(__file__)
app.mount('/static', StaticFiles(directory=os.path.join(BASE, 'static')), name='static')
templates = Jinja2Templates(directory=os.path.join(BASE, 'templates'))


def is_authenticated(request: Request):
    return request.session.get('authenticated') is True


def protected(request: Request):
    if not is_authenticated(request):
        raise HTTPException(status_code=401, detail='Please sign in')


def csrf_token(request: Request):
    if not request.session.get('csrf'):
        request.session['csrf'] = secrets.token_urlsafe(32)
    return request.session['csrf']


def check_csrf(request: Request, value: str):
    if not is_authenticated(request) or not secrets.compare_digest(value, request.session.get('csrf', '')):
        raise HTTPException(status_code=403, detail='Invalid CSRF token')


def page(request: Request, template: str, **context):
    return templates.TemplateResponse(request, template, {
        'request': request, 'csrf': csrf_token(request),
        'jellyfin_public_url': cfg.jellyfin_public_url.rstrip('/'), **context,
    })


@app.get('/healthz')
def healthz(db: Session = Depends(get_db)):
    db.execute(text('SELECT 1'))
    return {'ok': True}


@app.get('/login', response_class=HTMLResponse)
def login_form(request: Request):
    if is_authenticated(request):
        return RedirectResponse('/', status_code=303)
    return templates.TemplateResponse(request, 'login.html', {'request': request, 'error': False})


@app.post('/login')
def login(request: Request, username: str = Form(''), password: str = Form('')):
    valid_user = secrets.compare_digest(username.encode(), cfg.app_username.encode())
    valid_pass = secrets.compare_digest(password.encode(), cfg.app_password.encode())
    if not (valid_user and valid_pass):
        return templates.TemplateResponse(request, 'login.html', {'request': request, 'error': True}, status_code=401)
    request.session.clear()
    request.session['authenticated'] = True
    request.session['csrf'] = secrets.token_urlsafe(32)
    return RedirectResponse('/', status_code=303)


@app.post('/logout')
def logout(request: Request, csrf: str = Form('')):
    check_csrf(request, csrf)
    request.session.clear()
    return RedirectResponse('/login', status_code=303)


@app.get('/', response_class=HTMLResponse)
def index(request: Request, q: str = '', filter: str = 'available', page_no: int = Query(1, ge=1, le=10000),
          db: Session = Depends(get_db)):
    if not is_authenticated(request):
        return RedirectResponse('/login', status_code=303)
    query = select(Anime)
    if filter == 'available':
        query = query.where(Anime.available.is_(True))
    elif filter == 'review':
        query = query.where(Anime.match_status.in_(['needs_review', 'unmatched']))
    elif filter == 'rated':
        query = query.where(Anime.personal_rating.isnot(None))
    elif filter != 'all':
        filter = 'available'
        query = query.where(Anime.available.is_(True))
    if q:
        query = query.where(or_(Anime.title.ilike(f'%{q[:120]}%'), Anime.source_title.ilike(f'%{q[:120]}%')))
    query = query.order_by(Anime.title.asc())
    total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
    records = db.scalars(query.offset((page_no - 1)*48).limit(48)).all()
    return page(request, 'index.html', rows=records, q=q, filter=filter, page_no=page_no,
                total=total, has_next=page_no*48 < total,
                last_sync=read_state(db, 'last_jellyfin_sync', 'never'),
                last_error=read_state(db, 'last_error'))


@app.get('/anime/{anime_id}', response_class=HTMLResponse)
def anime_detail(request: Request, anime_id: str, db: Session = Depends(get_db)):
    if not is_authenticated(request):
        return RedirectResponse('/login', status_code=303)
    anime = db.get(Anime, anime_id)
    if anime is None:
        raise HTTPException(404, 'Unknown title')
    eps = db.scalars(select(Episode).where(Episode.anime_id == anime_id)
                     .order_by(Episode.season.asc().nullslast(), Episode.number.asc().nullslast())).all()
    local = {a.anilist_id: a for a in db.scalars(select(Anime).where(Anime.anilist_id.isnot(None), Anime.available.is_(True))).all()}
    related = [(r, local.get(r['id'])) for r in (anime.relations or [])]
    return page(request, 'detail.html', anime=anime, eps=eps, related=related,
                audio_counts=episode_audio_counts(eps))


@app.post('/anime/{anime_id}/review')
def save_review(request: Request, anime_id: str, csrf: str = Form(''),
                rating: str = Form(''), review: str = Form(''), db: Session = Depends(get_db)):
    check_csrf(request, csrf)
    anime = db.get(Anime, anime_id)
    if not anime:
        raise HTTPException(404)
    if rating.strip():
        try:
            number = float(rating)
        except ValueError:
            raise HTTPException(422, 'Rating must be a number from 0 to 10')
        if not 0 <= number <= 10:
            raise HTTPException(422, 'Rating must be between 0 and 10')
        anime.personal_rating = round(number, 1)
    else:
        anime.personal_rating = None
    anime.personal_review = review[:30000]
    db.commit()
    return RedirectResponse('/anime/' + quote(anime_id), status_code=303)


@app.post('/anime/{anime_id}/match')
def set_match(request: Request, anime_id: str, csrf: str = Form(''),
              anilist_id: str = Form(''), db: Session = Depends(get_db)):
    check_csrf(request, csrf)
    anime = db.get(Anime, anime_id)
    if not anime:
        raise HTTPException(404)
    try:
        media_id = int(anilist_id)
    except ValueError:
        raise HTTPException(422, 'AniList ID must be a positive integer')
    if not 1 <= media_id <= 10_000_000:
        raise HTTPException(422, 'AniList ID out of range')
    anime.anilist_id = media_id
    anime.match_status = 'manual'
    anime.match_confidence = 1.0
    anime.enriched_at = None
    anime.title = anime.source_title
    put_state(db, 'sync_requested', '1')
    db.commit()
    return RedirectResponse('/anime/' + quote(anime_id), status_code=303)


@app.post('/sync')
def request_sync(request: Request, csrf: str = Form(''), db: Session = Depends(get_db)):
    check_csrf(request, csrf)
    put_state(db, 'sync_requested', '1')
    db.commit()
    return RedirectResponse('/', status_code=303)


@lru_cache(maxsize=1)
def jellyfin_image_client():
    # Reuse keep-alive connections instead of opening one TCP pool per poster.
    return JellyfinClient()


@app.get('/poster/{anime_id}')
def poster(request: Request, anime_id: str, db: Session = Depends(get_db)):
    protected(request)
    anime = db.get(Anime, anime_id)
    if not anime:
        raise HTTPException(404)
    try:
        result = jellyfin_image_client().image(anime.id)
    except (httpx.HTTPError, ValueError):
        result = None
    if result:
        image_bytes, content_type = result
        return Response(image_bytes, media_type=content_type, headers={'Cache-Control': 'private, max-age=3600'})
    if anime.cover_url and anime.cover_url.startswith('https://'):
        return RedirectResponse(anime.cover_url, status_code=302)
    raise HTTPException(404)


@app.get('/sidecars', response_class=HTMLResponse)
def sidecars(request: Request, db: Session = Depends(get_db)):
    if not is_authenticated(request):
        return RedirectResponse('/login', status_code=303)
    rows = db.scalars(select(Sidecar).order_by(Sidecar.release, Sidecar.relative_path).limit(500)).all()
    total = db.scalar(select(func.count()).select_from(Sidecar))
    return page(request, 'sidecars.html', rows=rows, total=total)


@app.get('/api/anime')
def api_anime(request: Request, db: Session = Depends(get_db)):
    protected(request)
    items = db.scalars(select(Anime).where(Anime.available.is_(True)).order_by(Anime.title)).all()
    return [{'id': a.id, 'title': a.title, 'episodes': a.file_count,
             'total_episodes': a.total_episodes, 'audio_languages': a.audio_languages,
             'rating': a.personal_rating, 'anilist_id': a.anilist_id} for a in items]


@app.get('/api/status')
def api_status(request: Request, db: Session = Depends(get_db)):
    protected(request)
    return {key: read_state(db, key) for key in ('last_jellyfin_sync', 'last_jellyfin_count',
            'last_enrichment', 'last_sidecar_sync', 'sidecar_count', 'last_error')}
