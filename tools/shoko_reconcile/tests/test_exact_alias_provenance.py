"""Regression tests for exact anime aliases preserved across Shoko ranking."""
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from auto_fallback import auto_link_rejection_reason
from matching import rank_candidates
from refinements import refine, unique_exact_work_candidate


class ExactAliasProvenanceTests(unittest.TestCase):
    def test_shoko_titles_survive_ranking_even_if_another_query_wins(self):
        raw = [{"anidb_id": 999, "title": "Example II", "type": "TV",
                "Titles": [{"Name": "Example 2nd Season"}]}]
        # The first generated query matches the canonical title at 1.0;
        # an equally exact full-release alias is not the best fuzzy alias.
        ranked = rank_candidates(
            ["Example II", "Example 2nd Season"], raw,
            folder="Example 2nd Season", season=2)
        self.assertEqual(len(ranked), 1)
        self.assertEqual(ranked[0]["matched_alias"], "Example II")
        self.assertEqual(ranked[0]["Titles"], raw[0]["Titles"])
        group = {"folder": "Example 2nd Season", "candidates": ranked}
        self.assertEqual(unique_exact_work_candidate(group)["anidb_id"], 999)

        row = {"file_id": 1, "path": "Example 2nd Season/Example - 01.mkv",
               "source_episode": 1, "episode": 1, "episode_type": "Episode",
               "target_anidb_id": 999, "mode": "auto_evidence"}
        group.update({"files": [row], "mode": "auto_evidence",
                      "title_guess": "Example 2nd Season",
                      "queries": ["Example 2nd Season"]})
        result = refine({"version": 2, "groups": [group]}, records=[])
        promoted = result["groups"][0]["files"][0]
        self.assertEqual(promoted["mode"], "exact_work_title")
        self.assertIsNone(auto_link_rejection_reason(result["groups"][0], promoted))

    def test_offline_catalog_exact_synonym_is_not_lost(self):
        raw = [{"anidb_id": 1001, "title": "Sample II", "type": "TV",
                "aliases": ["Sample 2nd Season"]}]
        ranked = rank_candidates(
            ["Sample II", "Sample 2nd Season"], raw,
            folder="Sample 2nd Season", season=2)
        self.assertEqual(ranked[0]["matched_alias"], "Sample II")
        self.assertEqual(ranked[0]["aliases"], ["Sample 2nd Season"])
        self.assertEqual(unique_exact_work_candidate({
            "folder": "Sample 2nd Season", "candidates": ranked})["anidb_id"], 1001)

    def test_shared_exact_alias_across_two_works_remains_ambiguous(self):
        group = {"folder": "Example 2nd Season",
                 "candidates": [
                     {"anidb_id": 10, "title": "Example II", "type": "TV",
                      "season": 2, "Titles": ["Example 2nd Season"]},
                     {"anidb_id": 11, "title": "Example (2024)", "type": "TV",
                      "season": 2, "aliases": ["Example 2nd Season"]}]}
        self.assertIsNone(unique_exact_work_candidate(group))

    def test_exact_shared_franchise_root_must_not_promote_sequel(self):
        group = {"folder": "Example", "candidates": [
            {"anidb_id": 10, "title": "Example II", "type": "TV",
             "season": 2, "aliases": ["Example"]}]}
        self.assertIsNone(unique_exact_work_candidate(group))

    def test_ova_type_conflict_must_not_promote_tv(self):
        group = {"folder": "Example OVA", "candidates": [
            {"anidb_id": 10, "title": "Example", "type": "TV",
             "aliases": ["Example OVA"]}]}
        self.assertIsNone(unique_exact_work_candidate(group))


if __name__ == "__main__":
    unittest.main()
