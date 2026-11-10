from pathlib import Path
from types import SimpleNamespace
from app.media import episode_audio_counts
from app.config import Settings


def test_audio_counts_are_language_agnostic_and_deduplicated():
    eps = [SimpleNamespace(id='a', season=1, number=1, audio_languages=['jpn', 'eng']),
           SimpleNamespace(id='b', season=1, number=1, audio_languages=['jpn']),
           SimpleNamespace(id='c', season=1, number=2, audio_languages=['jpn']),
           SimpleNamespace(id='d', season=0, number=1, audio_languages=['deu'])]
    assert episode_audio_counts(eps) == {'eng': 1, 'jpn': 2}


def test_configuration_has_no_target_audio_locale():
    assert 'target_audio_language' not in Settings.model_fields
    env = Path('.env.example').read_text()
    assert 'TARGET_AUDIO_LANGUAGE=' not in env


def test_english_interface_and_true_black_tokens():
    templates = Path('app/templates')
    assert '<html lang="en">' in (templates / 'base.html').read_text()
    css = Path('app/static/style.css').read_text()
    assert 'html[data-theme="amoled"]' in css
    assert '--bg:#000' in css and '--panel:#000' in css
    for file in templates.glob('*.html'):
        assert 'Kotaru Anime' not in file.read_text()
