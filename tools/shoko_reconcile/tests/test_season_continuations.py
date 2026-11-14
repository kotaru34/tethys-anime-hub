"""End-to-end source-numbered 13+13 seasons with live Shoko evidence."""
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from auto_fallback import auto_link_rejection_reason, keep_safe_rows
from local_siblings import promote_linked_siblings, demote_nonexistent_sibling_episodes
from season_continuations import promote_verified_second_season, verify_split_row
from shoko_reconcile import apply


def plan(*nums, folder="Example", aid=777):
    return {"version": 2, "groups": [{
        "folder": folder,
        "candidates": [{"anidb_id": aid, "title": folder, "score": 1.0}],
        "files": [{"file_id": 100 + n, "path": f"{folder}/{folder} - {n:02}.mkv",
                   "episode": n, "source_episode": n, "episode_type": "Episode",
                   "target_anidb_id": aid, "mode": "auto_evidence"}
                  for n in nums]
    }]}


class API:
    def __init__(self, season2=True):
        self.season2 = season2
        self.linked = []
        self.searches = 0
        self.anchors = [
            {"ID": i, "Locations": [{"RelativePath": f"Example/Example - {i:02}.mkv"}],
             "SeriesIDs": [{"SeriesID": {"AniDB": 777}, "EpisodeIDs": [{"ID": i + 10000}]}]}
            for i in range(1, 14)
        ]
    def pages(self, path, params=None, size=500):
        assert path == "/File" and params == {"include": "XRefs"}
        yield from self.anchors
    def local_series(self, aid):
        ids = {777: 77, 999: 99}
        sid = ids.get(aid)
        return {"IDs": {"AniDB": aid, "ID": sid}} if sid else None
    def available_episodes(self, sid):
        return {("Episode", n) for n in range(1, 14)}
    def anime_search(self, title):
        self.searches += 1
        return ([{"ID": 999, "Title": "Example 2nd Season", "Type": "TV"},
                 {"ID": 777, "Title": "Example", "Type": "TV"}]
                if self.season2 else [{"ID": 777, "Title": "Example", "Type": "TV"}])
    def unrecognized(self):
        return [{"ID": 100 + n, "Locations": [{
            "RelativePath": f"Example/Example - {n:02}.mkv"}]}
            for n in range(14, 27)]
    def link(self, fid, sid, ep, kind):
        self.linked.append((fid, sid, ep, kind))
    def refresh_series(self, aid):
        raise AssertionError("Local series data are already available")


class ContinuationTests(unittest.TestCase):
    def test_exact_13_plus_13_split_links_to_independent_s2_e1_to_e13(self):
        api = API()
        p = plan(*range(14, 27))
        unknown = {r["file_id"] for r in p["groups"][0]["files"]}
        promote_linked_siblings(api, p, unknown)
        self.assertEqual(promote_verified_second_season(api, p, unknown), 13)
        self.assertEqual(demote_nonexistent_sibling_episodes(api, p), 0)
        g = p["groups"][0]
        for n, row in enumerate(g["files"], start=14):
            self.assertEqual(row["target_anidb_id"], 999)
            self.assertEqual(row["episode"], n - 13)
            self.assertEqual(row["source_episode"], n)
            self.assertEqual(row["mode"], "verified_second_season")
            self.assertIsNone(auto_link_rejection_reason(g, row))
            self.assertTrue(verify_split_row(api, g, row))
        safe, rejected = keep_safe_rows(p, unknown)
        self.assertEqual(rejected, 0)
        result = apply(api, safe, delay=0)
        self.assertEqual(result["submitted"], 13)
        self.assertEqual(api.linked[0], (114, 99, 1, "Episode"))
        self.assertEqual(api.linked[-1], (126, 99, 13, "Episode"))

    def test_without_exact_second_work_never_remap_or_link_overflow(self):
        api = API(season2=False)
        p = plan(*range(14, 27))
        unknown = {r["file_id"] for r in p["groups"][0]["files"]}
        promote_linked_siblings(api, p, unknown)
        self.assertEqual(promote_verified_second_season(api, p, unknown), 0)
        self.assertEqual(demote_nonexistent_sibling_episodes(api, p), 13)
        self.assertEqual([r["mode"] for r in p["groups"][0]["files"]],
                         ["episode_review"] * 13)

    def test_single_episode_after_tv_cannot_look_like_s2_without_block(self):
        api = API()
        p = plan(14)
        self.assertEqual(promote_verified_second_season(api, p, {114}), 0)
        self.assertEqual(api.searches, 0)

    def test_bad_stored_split_cannot_be_applied(self):
        api = API()
        p = plan(*range(14, 17))
        unknown = {r["file_id"] for r in p["groups"][0]["files"]}
        self.assertEqual(promote_verified_second_season(api, p, unknown), 3)
        p["groups"][0]["files"][0]["target_anidb_id"] = 123456
        result = apply(api, p, delay=0)
        self.assertEqual(result["deferred_by_reason"].get("sequel_split_live_proof_missing"), 1)
        self.assertNotIn((114, 99, 1, "Episode"), api.linked)


if __name__ == "__main__":
    unittest.main()
