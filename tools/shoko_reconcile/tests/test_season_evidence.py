"""Season identity regressions: synthetic cases, no private anime inventory."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path
from threading import Event

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from matching import (classify_episode, group_season_evidence,
                      season_aware_queries, rank_candidates,
                      target_season_supported)
from shoko_reconcile import analyze_report, prepare
from auto_fallback import is_safe_automatic_link
from event_bridge import Coordinator


BASE = {"anidb_id": 101, "title": "Galactic Harbor: Quick Sailing!",
        "type": "TV", "year": 2021, "episodes": 12}
SECOND = {"anidb_id": 102, "title": "Galactic Harbor: Quick Sailing! Ni!!",
          "aliases": ["Galactic Harbor: Slow Ahead! 2"],
          "type": "TV", "year": 2026, "episodes": 12}
THIRD = {"anidb_id": 103, "title": "Galactic Harbor: Quick Sailing! Season 3",
         "type": "TV", "year": 2028, "episodes": 12}


def source_files(folder, season=2, count=12):
    return [
        {"file_id": i, "path": f"{folder}/[Fansub] Galactic Harbor - S{season:02}E{i:02} [1080p].mkv"}
        for i in range(1, count + 1)
    ]


class FakeCatalog:
    def lookup(self, query):
        return [dict(x) for x in (BASE, SECOND, THIRD)]


class FakeAPI:
    def __init__(self, folder, files):
        self.folder = folder
        self.files = [
            {"ID": f["file_id"],
             "Locations": [{"RelativePath": f["path"]}]}
            for f in files
        ]
        self.queries = []

    def unrecognized(self):
        return self.files

    def pages(self, path):
        assert path == "/File"
        return iter(self.files)

    def anime_search(self, title):
        self.queries.append(title)
        return [{"ID": BASE["anidb_id"], "Title": BASE["title"], "Type": BASE["type"]},
                {"ID": SECOND["anidb_id"], "Title": SECOND["title"], "Type": SECOND["type"]}]


class SeasonEvidenceTests(unittest.TestCase):
    def test_file_season_overrides_untagged_folder(self):
        folder = "Galactic Harbor: Quick Sailing!"
        files = source_files(folder, season=2)
        self.assertEqual(group_season_evidence(folder, files), (2, False))
        self.assertIn("Galactic Harbor: Quick Sailing! Season 2",
                      season_aware_queries(folder, files, [folder]))

    def test_chronology_resolves_sequel_that_uses_non_numeric_japanese_suffix(self):
        folder = "Galactic Harbor: Quick Sailing!"
        ranked = rank_candidates([folder, folder + " Season 2"],
                                 [BASE, SECOND, THIRD], folder=folder, season=2)
        self.assertEqual(ranked[0]["anidb_id"], SECOND["anidb_id"])
        self.assertEqual(ranked[0]["season"], 2)
        self.assertNotIn(BASE["anidb_id"], {c["anidb_id"] for c in ranked})

    def test_full_live_discovery_uses_s02_and_not_s01(self):
        folder = "Galactic Harbor: Quick Sailing!"
        api = FakeAPI(folder, source_files(folder))
        plan = prepare(api, {}, catalog=FakeCatalog())
        rows = plan["groups"][0]["files"]
        self.assertEqual({r["target_anidb_id"] for r in rows}, {102})
        self.assertEqual({r["episode"] for r in rows}, set(range(1, 13)))
        self.assertTrue(all(target_season_supported(plan["groups"][0], r) for r in rows))
        self.assertEqual(plan["metrics"]["potential_links_before_api_validation"], 12)

    def test_first_season_remains_eligible(self):
        folder = "Galactic Harbor: Quick Sailing!"
        ranked = rank_candidates([folder], [BASE, SECOND], folder=folder, season=1)
        self.assertEqual(ranked[0]["anidb_id"], 101)
        group = {"folder": folder, "candidates": [{"anidb_id": 101, "title": BASE["title"],
                 "score": 1, "season": 1}]}
        row = {"path": source_files(folder, season=1, count=1)[0]["path"],
               "target_anidb_id": 101, "episode": 1, "source_episode": 1,
               "episode_type": "Episode", "mode": "auto_evidence"}
        self.assertTrue(is_safe_automatic_link(group, row))

    def test_stale_plan_cannot_link_s02_to_s01_even_when_scores_are_perfect(self):
        folder = "Galactic Harbor: Quick Sailing!"
        group = {"folder": folder, "candidates": [
            {"anidb_id": 101, "title": BASE["title"], "score": 1.0, "season": 1},
            {"anidb_id": 102, "title": SECOND["title"], "score": 0.5, "season": 2},
        ]}
        row = {"path": source_files(folder, season=2, count=1)[0]["path"],
               "target_anidb_id": 101, "episode": 1, "source_episode": 1,
               "episode_type": "Episode", "mode": "auto_evidence"}
        self.assertFalse(target_season_supported(group, row))
        self.assertFalse(is_safe_automatic_link(group, row))

    def test_conflicting_seasons_are_not_one_consensus(self):
        folder = "Galactic Harbor: Quick Sailing!"
        files = source_files(folder, season=1, count=1) + [
            {"file_id": 2, "path": folder + "/Galactic Harbor S02E02.mkv"}]
        self.assertEqual(group_season_evidence(folder, files), (None, True))

    def test_season_folder_and_file_disagreement_is_conflict(self):
        folder = "Galactic Harbor: Quick Sailing! (Season 2)"
        self.assertEqual(group_season_evidence(folder, source_files(folder, season=1, count=1)),
                         (None, True))

    def test_old_v2_plan_is_not_promoted_from_s02_to_first_season(self):
        folder = "Galactic Harbor: Quick Sailing!"
        old = {
            "version": 2, "source_total_files_at_scan": 12, "groups": [{
                "folder": folder, "title_guess": folder,
                "selected_anidb_id": 101, "mode": "auto_evidence",
                "candidates": [{"anidb_id": 101, "title": BASE["title"], "score": 1.0}],
                "files": [{
                    "file_id": 1, "path": source_files(folder)[0]["path"],
                    "episode": 1, "source_episode": 1,
                    "episode_type": "Episode", "target_anidb_id": 101,
                    "mode": "auto_evidence", "reason": ""
                }]
            }]
        }
        from refinements import refine
        result = refine(old)
        row = result["groups"][0]["files"][0]
        self.assertIsNone(row["target_anidb_id"])
        self.assertEqual(row["mode"], "episode_review")

    def test_queue_idle_transition_schedules_reconciliation_without_file_event(self):
        c = object.__new__(Coordinator)
        c.idle = Event()
        c.pending = Event()
        c.received("Queue:QueueStateChanged", [
            {"TotalCount": 3, "CurrentlyExecuting": [], "Running": True}
        ])
        self.assertFalse(c.pending.is_set())
        c.received("Queue:QueueStateChanged", [
            {"TotalCount": 0, "CurrentlyExecuting": [], "Running": True}
        ])
        self.assertTrue(c.pending.is_set())
        c.pending.clear()
        c.received("Queue:QueueStateChanged", [
            {"TotalCount": 0, "CurrentlyExecuting": [], "Running": True}
        ])
        self.assertFalse(c.pending.is_set())


if __name__ == "__main__":
    unittest.main()
