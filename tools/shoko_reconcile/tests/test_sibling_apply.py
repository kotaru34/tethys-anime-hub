"""Regression: apply() accepts live-verified sibling identity, not fuzzy season score.

A previous workflow promoted sibling_consensus in auto_fallback then silently
deferred it under target_season_supported() in apply(). This reproduces that
mismatch and verifies end-to-end only genuine AniDB episode existence is linked.
"""
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from auto_fallback import is_safe_automatic_link
from local_siblings import promote_linked_siblings
from shoko_reconcile import apply


def anchor(fid, rel, aid=777):
    return {
        "ID": fid, "Locations": [{"RelativePath": rel}],
        "SeriesIDs": [{"SeriesID": {"AniDB": aid}, "EpisodeIDs": [{"ID": fid + 1000}]}]
    }


def prepared_plan():
    return {"version": 2, "groups": [{
        "folder": "Example S02", "candidates": [], "files": [{
            "file_id": 100, "path": "Example S02/Example S02E03.mkv",
            "target_anidb_id": 777, "episode": 3, "episode_type": "Episode",
            "source_episode": 3, "mode": "sibling_consensus",
            "sibling_evidence_count": 2
        }]
    }]}


class API:
    def __init__(self, episode_set=None, conflict=False):
        self.episode_set = episode_set if episode_set is not None else {
            ("Episode", 1), ("Episode", 2), ("Episode", 3)}
        self.anchors = [
            anchor(10, "Example S02/Example S02E01.mkv"),
            anchor(11, "Example S02/Example S02E02.mkv", aid=999 if conflict else 777)
        ]
        self.links = []
        self.requests = []
    def unrecognized(self):
        return [{"ID": 100, "Locations": [
            {"RelativePath": "Example S02/Example S02E03.mkv"}]}]
    def pages(self, path, params=None, size=500):
        assert path == "/File" and params == {"include": "XRefs"}
        self.requests.append(("pages", path))
        yield from self.anchors
    def local_series(self, aid):
        self.requests.append(("series", aid))
        return {"IDs": {"ID": 72, "AniDB": aid}}
    def available_episodes(self, sid):
        self.requests.append(("episodes", sid))
        return self.episode_set
    def refresh_series(self, aid):
        raise AssertionError("No refresh necessary when series and episodes exist")
    def link(self, fid, sid, ep, kind):
        self.links.append((fid, sid, ep, kind))


class ApplySiblingConsensusTests(unittest.TestCase):
    def test_live_consensus_allows_link_even_without_ranked_season_candidate(self):
        p = prepared_plan()
        row = p["groups"][0]["files"][0]
        self.assertTrue(is_safe_automatic_link(p["groups"][0], row))
        api = API()
        result = apply(api, p, delay=0)
        self.assertEqual(result["submitted"], 1)
        self.assertEqual(result["deferred"], 0)
        self.assertEqual(result["awaiting_series_refresh"], 0)
        self.assertEqual(api.links, [(100, 72, 3, "Episode")])

    def test_cached_live_sibling_index_avoids_second_full_file_scan(self):
        api = API()
        from local_siblings import sibling_index
        index = sibling_index(api)
        result = apply(api, prepared_plan(), delay=0, sibling_reference=index)
        self.assertEqual(result["submitted"], 1)
        self.assertEqual(api.requests.count(("pages", "/File")), 1)

    def test_conflicting_sibling_work_prevents_link(self):
        api = API(conflict=True)
        result = apply(api, prepared_plan(), delay=0)
        self.assertEqual(result["submitted"], 0)
        self.assertEqual(result["deferred_by_reason"], {
            "sibling_consensus_changed_since_plan": 1})
        self.assertEqual(api.links, [])

    def test_eligible_work_but_nonexistent_episode_stays_deferred(self):
        api = API(episode_set={("Episode", 1), ("Episode", 2)})
        result = apply(api, prepared_plan(), delay=0)
        self.assertEqual(result["submitted"], 0)
        self.assertEqual(result["deferred"], 1)
        self.assertEqual(result["deferred_by_reason"], {
            "episode_number_or_type_absent_in_anidb": 1})
        self.assertEqual(result["awaiting_series_refresh"], 0)
        self.assertEqual(api.links, [])

    def test_final_apply_reports_stale_file_and_does_not_link(self):
        api = API()
        p = prepared_plan()
        p["groups"][0]["files"][0]["path"] = "Example S02/renamed.mkv"
        result = apply(api, p, delay=0)
        self.assertEqual(result["deferred_by_reason"], {"source_path_changed": 1})
        self.assertFalse(api.links)


if __name__ == "__main__":
    unittest.main()
