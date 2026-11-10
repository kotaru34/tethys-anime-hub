from app.media import provider_id, release_group, streams, summarize_episodes, is_real_item
from app.subtitles import subtitle_hint, inventory
from app.sources import score_candidate, choose_candidate


def test_provider_case_insensitive():
    assert provider_id({'AniDB': '14567'}, 'anidb') == 14567
    assert provider_id({'AniList': 'oops'}, 'anilist') is None


def test_streams_and_dubbed_dedup():
    streams_1 = [{'Type': 'Audio', 'Language': 'jpn'}, {'Type': 'Audio', 'Language': 'ukr'},
                 {'Type': 'Subtitle', 'Language': 'eng'}]
    data = [
        {'Id': '1', 'ParentIndexNumber': 1, 'IndexNumber': 1, 'MediaSources': [{'MediaStreams': streams_1}]},
        {'Id': '2', 'ParentIndexNumber': 1, 'IndexNumber': 1, 'MediaSources': [{'MediaStreams': [{'Type': 'Audio', 'Language': 'jpn'}]}]},
        {'Id': '3', 'ParentIndexNumber': 1, 'IndexNumber': 2, 'MediaSources': [{'MediaStreams': [{'Type': 'Audio', 'Language': 'jpn'}]}]},
    ]
    out = summarize_episodes(data, 'ukr')
    assert out['file_count'] == 2
    assert out['dubbed_count'] == 1
    assert out['audio_languages'] == ['jpn', 'ukr']
    assert out['subtitle_languages'] == ['eng']


def test_release_group_and_missing():
    assert release_group('/Anime/show/[SubsPlease] Demo - 01.mkv') == 'SubsPlease'
    assert release_group('/Anime/show/episode01.mkv') is None
    assert not is_real_item({'LocationType': 'Virtual'})


def test_subtitles_read_only(tmp_path):
    root = tmp_path / 'Anime'
    release = root / '[GROUP] Some Show'
    (release / 'Subs').mkdir(parents=True)
    (release / '01.mkv').write_bytes(b'hi')
    (release / 'Subs' / '01.ukr.ass').write_bytes(b'[Script Info]')
    found = list(inventory(str(root)))
    assert len(found) == 1
    assert found[0]['release'] == '[GROUP] Some Show'
    assert found[0]['language_hint'] == 'ukr'
    assert found[0]['episode_hint'] == 1
    assert (release / 'Subs' / '01.ukr.ass').exists()


def test_candidate_safety_and_fuzzy(monkeypatch):
    class FakeAniList:
        def search(self, title):
            return [
                {'id': 123, 'title': {'romaji': 'Mahou Shoujo Lyrical Nanoha'}, 'seasonYear': 2004},
                {'id': 555, 'title': {'romaji': 'Mahou Shoujo Lyrical Nanoha StrikerS'}, 'seasonYear': 2007},
            ]
    assert score_candidate('Mahou Shoujo Lyrical Nanoha', FakeAniList().search('')[0], 2004) == 1.0
    mid, status, score, _ = choose_candidate('Mahou Shoujo Lyrical Nanoha', 2004, FakeAniList())
    assert mid == 123
    assert status == 'fuzzy'

def test_subtitle_languages_are_not_limited_to_a_favorite_list():
    assert subtitle_hint('02.spa.ass') == ('spa', 2)
    assert subtitle_hint('04.ita.srt') == ('ita', 4)
    assert subtitle_hint('08.zzq.ass')[0] is None
