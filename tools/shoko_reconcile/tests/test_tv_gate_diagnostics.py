"""Live-free regression tests for TV proof diagnostics and missing episodes."""
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from auto_fallback import (demote_missing_anidb_episodes, keep_safe_rows)
from verified_tv_batch import promote_verified_tv_batch


def group_for(folder, candidate, count):
    return {"folder": folder,
            "candidates": [candidate],
            "files": [
                {"file_id": n, "path": f"{folder}/{folder} - {n:02}.mkv",
                 "episode": n, "source_episode": n, "episode_type": "Episode",
                 "target_anidb_id": candidate["anidb_id"],
                 "mode": "strong_context"}
                for n in range(1, count + 1)]}


class NoApi:
    def local_series(self, aid):
        raise AssertionError("No metadata calls without exact title proof")


class EpisodeAPI:
    def __init__(self, episodes):
        self.episodes = episodes
        self.series_calls = self.episode_calls = 0

    def local_series(self, aid):
        self.series_calls += 1
        return {"IDs": {"AniDB": aid, "ID": 77}}

    def available_episodes(self, sid):
        self.episode_calls += 1
        return self.episodes


class TVDiagnosticTests(unittest.TestCase):
    def test_long_tv_with_no_matching_full_alias_shows_blocker(self):
        folder = "Konoyo no Hate de Koi o Utau Shoujo YU-NO"
        g = group_for(folder, {
            "anidb_id": 11, "title": "Entirely Different Series",
            "type": "TV", "score": 0.95}, 26)
        diag = {}
        self.assertEqual(promote_verified_tv_batch(
            NoApi(), {"groups": [g]}, {r["file_id"] for r in g["files"]},
            diagnostics=diag), 0)
        self.assertEqual(diag["screened_large_groups"], 1)
        self.assertEqual(diag["title_gate_reasons"], {"no_exact_full_title_alias": 1})
        self.assertEqual(diag["title_gate_examples"][0]["folder"], folder)
        self.assertEqual(diag["title_gate_examples"][0]["candidate_titles"],
                         ["Entirely Different Series"])

    def test_short_tv_with_two_identical_titles_remains_ambiguous(self):
        folder = "Nekopara"
        g = group_for(folder, {"anidb_id": 11, "title": folder,
                               "type": "Unknown", "score": 1}, 12)
        g["candidates"].append({"anidb_id": 22, "title": folder,
                                "type": "Unknown", "score": 1})
        diag = {}
        self.assertEqual(promote_verified_tv_batch(
            NoApi(), {"groups": [g]}, {r["file_id"] for r in g["files"]},
            diagnostics=diag), 0)
        self.assertEqual(diag["title_gate_reasons"],
                         {"multiple_exact_tv_work_ids": 1})

    def test_dated_sequel_root_alias_is_flagged_not_promoted(self):
        folder = "Konoyo no Hate de Koi o Utau Shoujo YU-NO"
        g = group_for(folder, {
            "anidb_id": 11, "title": "Kono Yo no Hate de Koi o Utau Shoujo YU-NO (2025)",
            "aliases": ["Kono Yo no Hate de Koi o Utau Shoujo YU-NO"],
            "type": "TV", "score": 1.0}, 26)
        diag = {}
        self.assertEqual(promote_verified_tv_batch(
            NoApi(), {"groups": [g]}, {r["file_id"] for r in g["files"]},
            diagnostics=diag), 0)
        self.assertEqual(diag["title_gate_reasons"], {"season_or_year_guard": 1})


class UnsupportedEpisodeTests(unittest.TestCase):
    @staticmethod
    def plan():
        group = {"folder": "Example",
                 "candidates": [],
                 "files": [
                     {"file_id": n, "path": f"Example/Example - {n:02}.mkv",
                      "episode": n, "source_episode": n, "episode_type": "Episode",
                      "target_anidb_id": 17477, "mode": "approved_release"}
                     for n in range(1, 6)]}
        return {"version": 2, "groups": [group]}

    def test_nonexistent_episodes_leave_approved_plan_and_enter_review(self):
        api = EpisodeAPI({("Episode", 1)})
        p = self.plan()
        missing = demote_missing_anidb_episodes(
            api, p, {r["file_id"] for r in p["groups"][0]["files"]})
        self.assertEqual([r["episode"] for r in missing], [2, 3, 4, 5])
        self.assertEqual((api.series_calls, api.episode_calls), (1, 1))
        safe, rejected = keep_safe_rows(p, {1, 2, 3, 4, 5})
        self.assertEqual(rejected, 4)
        self.assertEqual(len(safe["groups"][0]["files"]), 1)
        self.assertEqual(safe["groups"][0]["files"][0]["episode"], 1)
        self.assertTrue(all(r["mode"] == "episode_review"
                            for r in p["groups"][0]["files"][1:]))

    def test_empty_inflight_metadata_does_not_prove_episode_absence(self):
        api = EpisodeAPI(set())
        p = self.plan()
        self.assertEqual(demote_missing_anidb_episodes(
            api, p, {1, 2, 3, 4, 5}), [])
        safe, rejected = keep_safe_rows(p, {1, 2, 3, 4, 5})
        self.assertEqual(rejected, 0)
        self.assertEqual(len(safe["groups"][0]["files"]), 5)

    def test_unapproved_rows_do_not_consume_series_lookups(self):
        api = EpisodeAPI({("Episode", 1)})
        p = self.plan()
        for row in p["groups"][0]["files"]:
            row["mode"] = "episode_review"
        self.assertEqual(demote_missing_anidb_episodes(
            api, p, {1, 2, 3, 4, 5}), [])
        self.assertEqual(api.series_calls, 0)


if __name__ == "__main__":
    unittest.main()
