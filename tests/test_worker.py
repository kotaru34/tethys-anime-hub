from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from app.db import Base, Anime, Episode
from app import worker


class FakeClient:
    def catalog(self):
        shows = [{'Id': 'series1', 'Type': 'Series', 'Name': 'Nanoha',
                  'ProductionYear': 2004, 'ProviderIds': {'AniDB': '500'}}]
        episodes = {'series1': [
            {'Id': 'ep1', 'Name': 'Episode 1', 'SeriesId': 'series1',
             'ParentIndexNumber': 1, 'IndexNumber': 1, 'MediaSources': [
                 {'MediaStreams': [{'Type': 'Audio', 'Language': 'jpn'}]}]},
        ]}
        return shows, episodes


def test_sync_preserves_user_data(monkeypatch):
    engine = create_engine('sqlite+pysqlite://', connect_args={'check_same_thread': False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    Local = sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr(worker, 'SessionLocal', Local)
    assert worker.sync_jellyfin(FakeClient()) == 1
    with Local() as db:
        title = db.get(Anime, 'series1')
        assert title.file_count == 1
        assert title.anidb_id == 500
        title.personal_rating = 9.5
        title.personal_review = 'My personal notes remain here'
        db.commit()
    assert worker.sync_jellyfin(FakeClient()) == 1
    with Local() as db:
        title = db.get(Anime, 'series1')
        assert title.personal_rating == 9.5
        assert title.personal_review == 'My personal notes remain here'
        assert len(db.scalars(select(Episode)).all()) == 1
    engine.dispose()


def test_detail_data_and_relations():
    a = Anime(id='id1', title='Raw', source_title='Raw')
    worker._apply_detail(a, {
        'id': 5, 'title': {'english': 'Normalised'}, 'episodes': 12,
        'startDate': {'year': 2024, 'month': 4, 'day': 1},
        'studios': {'nodes': [{'name': 'Test Studio'}]},
        'relations': {'edges': [{'relationType': 'PREQUEL', 'node': {
            'id': 4, 'title': {'romaji': 'Earlier'}, 'format': 'OVA'
        }}]},
    })
    assert a.title == 'Normalised'
    assert a.total_episodes == 12
    assert a.relations[0]['title'] == 'Earlier'
    assert a.premiere == '2024-04-01'
