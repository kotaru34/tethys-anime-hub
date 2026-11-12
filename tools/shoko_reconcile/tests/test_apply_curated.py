"""Regression tests for safe curated links, using only synthetic data."""
from __future__ import annotations

import contextlib
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from apply_curated import load_mapping, run


class FakeAPI:
    def __init__(self):
        self.linked = []
        self.refreshed = []
        self.files = [
            {'ID': 1, 'Locations': [{'RelativePath': 'Example Anime/Ep 1.mkv'}]},
            {'ID': 2, 'Locations': [{'RelativePath': 'Example Anime/Trailer 1.mkv'}]},
        ]
        self.found = {100: {'IDs': {'ID': 200, 'AniDB': 100}, 'Name': 'Example Anime'}}
        self.available = {200: {('Special', 1), ('Trailer', 1)}}

    def unrecognized(self): return self.files
    def local_series(self, aid): return self.found.get(aid)
    def available_episodes(self, sid): return self.available.get(sid, set())
    def pages(self, path, params):
        return [
            {'AniDB': {'Type': 'Special', 'EpisodeNumber': 1, 'Title': 'Example recap'}},
            {'AniDB': {'Type': 'Trailer', 'EpisodeNumber': 1, 'Title': 'Episode 1 preview'}},
        ]
    def refresh_series(self, aid): self.refreshed.append(aid)
    def link(self, *args): self.linked.append(args)


class CuratedTests(unittest.TestCase):
    def setUp(self):
        self.api = FakeAPI()
        self.rows = [
            {'file_id': 1, 'anidb_id': 100, 'episode': 1, 'type': 'Special',
             'path_hint': 'Example Anime/Ep 1.mkv', 'rationale': 'recap',
             'expected_series_title_regex': 'example anime',
             'expected_episode_title_regex': 'recap',
             'requires_preview_opt_in': False},
            {'file_id': 2, 'anidb_id': 100, 'episode': 1, 'type': 'Trailer',
             'path_hint': 'Example Anime/Trailer 1.mkv', 'rationale': 'preview',
             'expected_series_title_regex': '', 'expected_episode_title_regex': '',
             'requires_preview_opt_in': True},
        ]

    def run_quiet(self, *args, **kwargs):
        # Keep CI and local tests independent of the production /root journal.
        with tempfile.TemporaryDirectory() as directory:
            kwargs.setdefault('journal', str(Path(directory) / 'audit.json'))
            with contextlib.redirect_stdout(io.StringIO()):
                return run(*args, **kwargs)

    def test_read_only_default(self):
        result = self.run_quiet(self.api, self.rows)
        self.assertEqual(result['ready'], 1)
        self.assertEqual(self.api.linked, [])

    def test_explicit_apply_omits_previews(self):
        with tempfile.TemporaryDirectory() as directory:
            result = self.run_quiet(self.api, self.rows, apply=True,
                                    journal=directory + '/audit.json')
            self.assertEqual(result['submitted'], 1)
            self.assertEqual(len(self.api.linked), 1)

    def test_preview_opt_in(self):
        with tempfile.TemporaryDirectory() as directory:
            result = self.run_quiet(self.api, self.rows, apply=True,
                                    include_previews=True, journal=directory + '/audit.json')
            self.assertEqual(result['submitted'], 2)

    def test_resolved_file_is_skipped(self):
        self.api.files = []
        result = self.run_quiet(self.api, self.rows, apply=True)
        self.assertEqual(result['submitted'], 0)

    def test_stale_path_prevents_write(self):
        self.api.files[0]['Locations'][0]['RelativePath'] = 'unrelated.mkv'
        result = self.run_quiet(self.api, self.rows, apply=True)
        self.assertEqual(result['submitted'], 0)

    def test_missing_episode_prevents_write(self):
        self.api.available = {200: set()}
        result = self.run_quiet(self.api, self.rows, apply=True)
        self.assertEqual(result['submitted'], 0)

    def test_episode_title_mismatch_prevents_write(self):
        self.rows[0]['expected_episode_title_regex'] = 'different'
        result = self.run_quiet(self.api, self.rows, apply=True)
        self.assertEqual(result['submitted'], 0)

    def test_series_title_mismatch_prevents_write(self):
        self.rows[0]['expected_series_title_regex'] = 'different'
        result = self.run_quiet(self.api, self.rows, apply=True)
        self.assertEqual(result['submitted'], 0)

    def test_refresh_only_requests_metadata(self):
        self.api.found = {}
        self.run_quiet(self.api, self.rows, refresh=True)
        self.assertEqual(self.api.refreshed, [100])
        self.assertEqual(self.api.linked, [])

    def test_json_schema_rejects_duplicates(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'mappings.json'
            path.write_text(json.dumps({'mappings': [self.rows[0]]}))
            self.assertEqual(len(load_mapping(path)), 1)
            path.write_text(json.dumps({'mappings': [self.rows[0], self.rows[0]]}))
            with self.assertRaises(ValueError):
                load_mapping(path)
