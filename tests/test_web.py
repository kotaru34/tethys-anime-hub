import os
os.environ['APP_PASSWORD'] = 'test-password-only'
os.environ['SESSION_SECRET'] = 'this-is-a-long-test-secret-only-for-local-tests-12345'
os.environ['DATABASE_URL'] = 'sqlite+pysqlite://'

from app.config import settings
settings.cache_clear()
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from app.db import Base, Anime, get_db
from app.web import app


def test_login_csrf_review_and_browse():
    engine = create_engine('sqlite+pysqlite://', connect_args={'check_same_thread': False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    local = sessionmaker(engine, expire_on_commit=False)
    with local() as db:
        db.add(Anime(id='s1', title='Demo', source_title='Demo', available=True,
                     file_count=3, audio_languages=['jpn'], subtitle_languages=['eng']))
        db.commit()

    def override():
        with local() as db:
            yield db

    app.dependency_overrides[get_db] = override
    try:
        with TestClient(app) as client:
            assert client.get('/').status_code == 200
            assert 'Вхід' in client.get('/').text
            assert client.post('/login', data={'username': 'admin', 'password': 'wrong'}).status_code == 401
            assert client.post('/login', data={'username': 'admin', 'password': 'test-password-only'}).status_code == 200
            page = client.get('/anime/s1').text
            assert 'Demo' in page
            import re
            token = re.search(r'name="csrf" value="([^"]+)"', page).group(1)
            assert client.post('/anime/s1/review', data={'csrf': 'bad', 'rating': '9'}).status_code == 403
            response = client.post('/anime/s1/review', data={'csrf': token, 'rating': '8.5', 'review': 'Great'})
            assert response.status_code == 200
            with local() as db:
                anime = db.get(Anime, 's1')
                assert anime.personal_rating == 8.5
                assert anime.personal_review == 'Great'
    finally:
        app.dependency_overrides.clear()
        engine.dispose()
