"""Tests for per-series metadata readiness without global queue idleness."""
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from shoko_reconcile import apply


class FakeAPI:
    def __init__(self):
        self.series = None
        self.episodes = set()
        self.refresh_calls = []
        self.links = []
    def unrecognized(self):
        return [{"ID": 37, "Locations": [{"RelativePath": "Example/E01.mkv"}]}]
    def local_series(self, aid):
        return self.series
    def refresh_series(self, aid):
        self.refresh_calls.append(aid)
    def available_episodes(self, sid):
        return self.episodes
    def link(self, fid, sid, ep, kind):
        self.links.append((fid, sid, ep, kind))


def plan():
    return {"version": 2, "groups": [{
        "folder": "Example", "candidates": [],
        "files": [{
            "file_id": 37, "path": "Example/E01.mkv",
            "target_anidb_id": 97531, "episode": 1,
            "episode_type": "Episode", "mode": "approved_release",
        }]
    }]}


class SelectiveMetadataTests(unittest.TestCase):
    def test_missing_series_metadata_does_not_wait_for_queue(self):
        api = FakeAPI()
        requests = {}
        one = apply(api, plan(), delay=0, refresh_requests=requests)
        self.assertEqual(one["awaiting_series_refresh"], 1)
        self.assertEqual(api.refresh_calls, [97531])
        self.assertEqual(len(requests), 1)
        # Two event-driven attempts must not enqueue duplicate metadata jobs.
        two = apply(api, plan(), delay=0, refresh_requests=requests)
        self.assertEqual(two["awaiting_series_refresh"], 1)
        self.assertEqual(api.refresh_calls, [97531])

    def test_known_series_but_no_episodes_yet_is_pending_not_failed(self):
        api = FakeAPI()
        api.series = {"IDs": {"AniDB": 97531, "ID": 72}}
        requests = {}
        result = apply(api, plan(), delay=0, refresh_requests=requests)
        self.assertEqual(result["awaiting_series_refresh"], 1)
        self.assertEqual(result["errors"], 0)
        self.assertEqual(api.refresh_calls, [97531])
        # Metadata arrives while Shoko is still fetching unrelated artwork:
        # apply must link immediately; it must not read global /Queue.
        api.episodes = {("Episode", 1)}
        result = apply(api, plan(), delay=0, refresh_requests=requests)
        self.assertEqual(result["submitted"], 1)
        self.assertEqual(api.links, [(37, 72, 1, "Episode")])

    def test_no_episode_identity_still_not_forced(self):
        api = FakeAPI()
        api.series = {"IDs": {"AniDB": 97531, "ID": 72}}
        api.episodes = {("Episode", 2)}
        result = apply(api, plan(), delay=0, refresh_requests={})
        self.assertEqual(result["submitted"], 0)
        self.assertEqual(result["deferred"], 1)
        self.assertEqual(api.links, [])


if __name__ == "__main__":
    unittest.main()
