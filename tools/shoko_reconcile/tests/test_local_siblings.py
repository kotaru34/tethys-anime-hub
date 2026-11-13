"""Conservative recognized-sibling evidence tests with synthetic Shoko API records."""
import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from local_siblings import promote_linked_siblings
from auto_fallback import is_safe_automatic_link


def file_record(fid, rel, aid=12345, *, linked=True, episode_ids=None):
    refs = ([{"SeriesID": {"AniDB": aid}, "EpisodeIDs": episode_ids or [{"ID": fid + 1000}]}]
            if linked else [])
    return {"ID": fid, "Locations": [{"RelativePath": rel}], "SeriesIDs": refs}


class API:
    def __init__(self, records):
        self.records = records
    def pages(self, path, params=None, size=500):
        assert path == "/File" and params == {"include": "XRefs"}
        yield from self.records


def plan_for(rel="Example/Example - 03.mkv", *, aid=None, mode="review"):
    return {"version": 2, "groups": [{
        "folder": "Example", "files": [{
            "file_id": 100, "path": rel, "episode": 3,
            "episode_type": "Episode", "target_anidb_id": aid, "mode": mode,
        }], "candidates": []
    }]}


class SiblingConsensusTests(unittest.TestCase):
    def test_two_distinct_recognized_episodes_promote_third(self):
        api = API([file_record(10, "Example/Example - 01.mkv"),
                   file_record(11, "Example/Example - 02.mkv"),
                   file_record(100, "Example/Example - 03.mkv", linked=False)])
        plan = plan_for()
        self.assertEqual(promote_linked_siblings(api, plan, {100}), 1)
        row = plan["groups"][0]["files"][0]
        self.assertEqual((row["mode"], row["target_anidb_id"], row["episode"]),
                         ("sibling_consensus", 12345, 3))
        self.assertTrue(is_safe_automatic_link(plan["groups"][0], row))

    def test_duplicate_encodes_of_one_episode_are_not_independent_evidence(self):
        api = API([file_record(10, "Example/Example - 01 1080p.mkv"),
                   file_record(11, "Example/Example - 01 720p.mkv")])
        self.assertEqual(promote_linked_siblings(api, plan_for(), {100}), 0)

    def test_conflicting_work_id_disqualifies_directory(self):
        api = API([file_record(10, "Example/Example - 01.mkv"),
                   file_record(11, "Example/Example - 02.mkv"),
                   file_record(12, "Example/Example - 04.mkv", aid=54321)])
        self.assertEqual(promote_linked_siblings(api, plan_for(), {100}), 0)

    def test_different_directory_is_not_sibling(self):
        api = API([file_record(10, "Example/Season 1/E01.mkv"),
                   file_record(11, "Example/Season 1/E02.mkv")])
        self.assertEqual(promote_linked_siblings(api, plan_for(), {100}), 0)

    def test_ambiguous_season_guard(self):
        api = API([file_record(10, "Example/Example S01E01.mkv"),
                   file_record(11, "Example/Example S01E02.mkv")])
        self.assertEqual(promote_linked_siblings(api, plan_for(), {100}), 0)

    def test_existing_different_title_work_requires_manual_review(self):
        api = API([file_record(10, "Example/Example - 01.mkv"),
                   file_record(11, "Example/Example - 02.mkv")])
        self.assertEqual(promote_linked_siblings(
            api, plan_for(aid=54321, mode="strong_context"), {100}), 0)

    def test_unnumbered_and_specials_never_piggyback(self):
        api = API([file_record(10, "Example/Example - 01.mkv"),
                   file_record(11, "Example/Example - 02.mkv")])
        plan = plan_for("Example/Trailer.mkv")
        plan["groups"][0]["files"][0]["episode"] = None
        plan["groups"][0]["files"][0]["episode_type"] = "Unknown"
        self.assertEqual(promote_linked_siblings(api, plan, {100}), 0)


if __name__ == "__main__":
    unittest.main()
