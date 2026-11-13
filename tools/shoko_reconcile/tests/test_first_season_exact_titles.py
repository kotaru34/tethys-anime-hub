"""S01 title evidence: avoid false negatives without weakening sequel boundaries."""
import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from matching import main_title_candidates, rank_candidates, choose_candidate, classify_episode
from shoko_reconcile import analyze_report, metrics


class ExactFirstSeasonTest(unittest.TestCase):
    def test_exact_alias_first_season_without_anidb_season_field(self):
        for folder, name, canonical in (
            ("[Anime Time] Jahy-sama wa Kujikenai! (Season 1) [1080p]",
             "Jahy-sama wa Kujikenai!", "The Great Jahy Will Not Be Defeated!"),
            ("[DKB] Arknights Reimei Zensou - (Season 01) [1080p]",
             "Arknights: Reimei Zensou", "Arknights: Prelude to Dawn"),
            ("[RigAV1] Akame ga Kill! S01 (COMPLETE) (BD 1080p AV1)",
             "Akame ga Kill!", "Akame ga Kill!"),
        ):
            with self.subTest(folder=folder):
                queries = main_title_candidates(folder, [
                    {"path": f"{folder}/[Group] {name} - S01E01.mkv"}])
                queries += [name]
                ranked = rank_candidates(queries, [
                    {"anidb_id": 101, "title": canonical, "aliases": [name],
                     "type": "TV"},
                    {"anidb_id": 102, "title": "Unrelated Work Season 1",
                     "type": "TV"},
                ], folder=folder, season=1)
                self.assertEqual(ranked[0]["anidb_id"], 101)
                self.assertEqual(ranked[0]["season"], 1)
                self.assertGreaterEqual(ranked[0]["score"], 0.91)
                selected, mode, _ = choose_candidate(
                    ranked, folder=folder,
                    parsed=[classify_episode(f"{folder}/[Group] {name} - S01E01.mkv", group=folder)])
                self.assertEqual(selected, 101)
                self.assertEqual(mode, "auto_evidence")

    def test_sequel_cannot_gain_first_season_from_shared_alias(self):
        ranked = rank_candidates(
            ["Galactic Voyage", "Galactic Voyage Season 1"],
            [{"anidb_id": 1, "title": "Galactic Voyage Season 2",
              "aliases": ["Galactic Voyage"], "type": "TV"},
             {"anidb_id": 2, "title": "Galactic Voyage",
              "type": "TV"}],
            folder="Galactic Voyage (Season 1)", season=1)
        self.assertEqual(ranked[0]["anidb_id"], 2)
        self.assertNotIn(1, [r["anidb_id"] for r in ranked])

    def test_dated_entry_without_release_year_not_inferred_first_season(self):
        ranked = rank_candidates(
            ["Galactic Voyage", "Galactic Voyage Season 1"],
            [{"anidb_id": 2, "title": "Galactic Voyage (2024)",
              "aliases": ["Galactic Voyage"], "year": 2024,
              "type": "TV"}],
            folder="Galactic Voyage (Season 1)", season=1)
        self.assertIsNone(ranked[0]["season"])
        self.assertEqual(ranked[0]["score"], 0.82)

    def test_already_supported_base_title_inference_still_works(self):
        # Existing code supported exact base-title work identity even if the
        # noisy release query itself still contained a '(Season 1)' suffix.
        ranked = rank_candidates(
            ["Galactic Voyage (Season 1)"],
            [{"anidb_id": 1, "title": "Galactic Voyage", "type": "TV"}],
            folder="Galactic Voyage (Season 1)", season=1)
        self.assertEqual(ranked[0]["season"], 1)

    def test_similar_but_not_exact_alias_not_promoted(self):
        ranked = rank_candidates(
            ["Galactic Journey (Season 1)"],
            [{"anidb_id": 1, "title": "Galactic Voyage", "type": "TV"}],
            folder="Galactic Journey (Season 1)", season=1)
        self.assertIsNone(ranked[0]["season"])
        self.assertLess(ranked[0]["score"], 0.85)


if __name__ == "__main__":
    unittest.main()
