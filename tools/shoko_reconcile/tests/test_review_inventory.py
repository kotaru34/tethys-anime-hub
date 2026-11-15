"""Read-only manual-review inventory tests: no full-file scans or writes."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from review_inventory import inspect, plan_work_ids


def plan():
    return {"version": 2, "source_unrecognized_at_scan": 58, "groups": [
        {"folder": "Nekopara", "selected_anidb_id": None,
         "candidates": [
             {"anidb_id": 12622, "title": "Nekopara", "score": 1},
             {"anidb_id": 14570, "title": "Nekopara", "score": 1},
             {"anidb_id": 99999, "title": "Other", "score": 0.62}]},
        {"folder": "Seishun Buta", "selected_anidb_id": 17640,
         "candidates": [{"anidb_id": 17640, "score": 1}]}]}


class FakeAPI:
    def __init__(self):
        self.calls = []

    def local_series(self, aid):
        self.calls.append(("local_series", aid))
        if aid == 12622:
            return None
        return {"IDs": {"ID": aid - 1, "AniDB": aid}}

    def available_episodes(self, sid):
        self.calls.append(("available_episodes", sid))
        if sid == 14569:
            return {("Episode", n) for n in range(1, 13)}
        return {("Episode", 1)}

    def anime_search(self, query):
        self.calls.append(("anime_search", query))
        return [{"ID": 18888, "Title": "Matching OVA", "Type": "OVA",
                 "ShokoID": None, "Titles": [
                     {"Name": "First synonym"}, {"Name": "Second synonym"}]}]

    def pages(self, *args, **kwargs):
        raise AssertionError("Cannot scan /File in this tool")

    def unrecognized(self, *args, **kwargs):
        raise AssertionError("Cannot scan files in this tool")

    def link(self, *args, **kwargs):
        raise AssertionError("Cannot write links in this tool")

    def refresh_series(self, *args, **kwargs):
        raise AssertionError("Cannot refresh metadata in this tool")


class InventoryReviewTests(unittest.TestCase):
    def test_candidate_pool_is_exact_identity_only(self):
        self.assertEqual(plan_work_ids(plan()), {12622, 14570, 17640})

    def test_targeted_reads_are_unique_and_bounded(self):
        api = FakeAPI()
        result = inspect(api, plan(), extra_ids=[11143, 14570],
                         searches=["KonoSuba S3 Bonus Stage"])
        self.assertEqual(result["planned_ids"], [11143, 12622, 14570, 17640])
        self.assertEqual(len([c for c in api.calls if c[0] == "local_series"]), 4)
        self.assertEqual(len([c for c in api.calls if c[0] == "available_episodes"]), 3)
        self.assertEqual(len([c for c in api.calls if c[0] == "anime_search"]), 1)
        self.assertEqual(result["api_scope"]["full_file_scan_calls"], 0)
        self.assertEqual(result["api_scope"]["write_or_refresh_calls"], 0)
        self.assertEqual(result["local_work_inventory"][1]["status"],
                         "not_in_local_shoko")
        self.assertEqual(len(result["local_work_inventory"][2]["episodes"]), 12)

    def test_missing_searches_can_be_disabled_and_no_new_queries(self):
        api = FakeAPI()
        result = inspect(api, plan(), searches=())
        self.assertEqual(result["title_search"], {})
        self.assertFalse(any(c[0] == "anime_search" for c in api.calls))

    def test_reject_unbounded_plan_or_title_search(self):
        api = FakeAPI()
        with self.assertRaises(ValueError):
            inspect(api, plan(), max_ids=2, searches=())
        with self.assertRaises(ValueError):
            inspect(api, plan(), searches=["a", "b"], max_searches=1)
        self.assertEqual(api.calls, [])

    def test_bad_plan_rejected_before_api_access(self):
        api = FakeAPI()
        with self.assertRaises(ValueError):
            inspect(api, {"version": 1}, searches=())
        self.assertEqual(api.calls, [])


if __name__ == "__main__":
    unittest.main()
