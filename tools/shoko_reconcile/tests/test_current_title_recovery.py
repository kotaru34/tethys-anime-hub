"""Regression fixtures for safe exact-title and season-specific AniDB recovery.

Public anime titles and synthetic paths only; no private inventory or API keys.
"""
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from auto_fallback import is_safe_automatic_link
from matching import clean_release_title, classify_episode
from refinements import refine, _choose_public_crosswalk, known_aliases


def plan(folder, file_names, candidates=None):
    rows = []
    for idx, name in enumerate(file_names):
        path = folder + "/" + name
        info = classify_episode(path, group=folder)
        rows.append({
            "file_id": idx + 1, "path": path, "source_episode": None,
            "episode": info.number, "episode_type": info.category,
            "target_anidb_id": None, "mode": "review",
            "reason": "synthetic fixture"
        })
    return {
        "version": 2, "source_total_files_at_scan": 1000,
        "source_unrecognized_at_scan": len(rows), "groups": [{
            "folder": folder, "title_guess": clean_release_title(folder),
            "selected_anidb_id": None, "mode": "review",
            "reason": "synthetic ambiguous result", "candidates": candidates or [],
            "files": rows, "count": len(rows)
        }]
    }


class KnownPublicTitleRecoveryTests(unittest.TestCase):
    def test_public_title_variants_select_correct_distinct_work(self):
        fixtures = [
            ("[Group] Horimiya [BDRip 1080p]", "Horimiya - 01.mkv", 15733),
            ("Maou Gakuin no Futekigousha [WEBRip 1080p HEVC]",
             "Maou_Gakuin_no_Futekigousha_[01].mkv", 15131),
            ("[Group] Yofukashi no Uta [WEB-DL 1080p]", "Yofukashi no Uta 01.mkv", 16971),
            ("[Group] ATRI -My Dear Moments- (Season 01) [1080p][HEVC x265 10bit][Multi-Subs]v2",
             "[Group] ATRI - S01E01v2.mkv", 17635),
            ("Itai no wa Iya nano de Bougyoryoku ni Kyokufuri Shitai to Omoimasu [WEBRip 1080p HEVC]",
             "Itai no wa Iya - 01.mkv", 14523),
            ("Maou Gakuin no Futekigousha S2 [WEBRip 1080p HEVC]",
             "Maou S02E01.mkv", 16101),
            ("Maou Gakuin no Futekigousha S2 Part 2 [WEBRip 1080p HEVC]",
             "Maou S02E01.mkv", 16102),
            ("[Group] Mahoutsukai Reimeiki (The Dawn of the Witch) (Season 1) [1080p]",
             "[Group] Mahoutsukai Reimeiki - S01E01.mkv", 16280),
        ]
        for folder, file_name, expected_id in fixtures:
            with self.subTest(folder=folder):
                group = refine(plan(folder, [file_name]))["groups"][0]
                row = group["files"][0]
                self.assertEqual(row["target_anidb_id"], expected_id,
                                 f"{folder}: {row}")
                self.assertEqual(row["mode"], "public_crosswalk")
                self.assertEqual(row["episode"], 1)
                self.assertTrue(is_safe_automatic_link(group, row),
                                f"{folder}: safe gate rejected {row}")

    def test_split_cours_distinct_and_correct(self):
        part1 = refine(plan("Maou Gakuin no Futekigousha S2",
                            ["Maou Gakuin S02E01.mkv"]))["groups"][0]
        part2 = refine(plan("Maou Gakuin no Futekigousha S2 Part 2",
                            ["Maou Gakuin S02E01.mkv"]))["groups"][0]
        self.assertEqual(part1["files"][0]["target_anidb_id"], 16101)
        self.assertEqual(part2["files"][0]["target_anidb_id"], 16102)

    def test_nested_explicit_season2_works_but_season_neutral_does_not(self):
        folder = "[Group] Mashle - Magic And Muscles"
        s2 = refine(plan(folder,
                         ["Season 2/Mashle - Magic And Muscles - S02E01.mkv"]))["groups"][0]
        self.assertEqual(s2["files"][0]["target_anidb_id"], 18088)
        self.assertTrue(is_safe_automatic_link(s2, s2["files"][0]))
        unknown = refine(plan(folder, ["Mashle - Magic And Muscles - 01.mkv"]))["groups"][0]
        self.assertNotEqual(unknown["files"][0]["target_anidb_id"], 18088)

    def test_mato_episode_revision_is_not_episode_number(self):
        self.assertEqual(classify_episode(
            "Mato Seihei no Slave/[Group] Mato Seihei no Slave - 10v3 [1080p].mkv",
            group="Mato Seihei no Slave").number, 10)
        group = refine(plan("Mato Seihei no Slave",
                            ["[Group] Mato Seihei no Slave - 10v3 [1080p].mkv"]))["groups"][0]
        self.assertEqual(group["files"][0]["target_anidb_id"], 16982)
        self.assertEqual(group["files"][0]["episode"], 10)
        self.assertTrue(is_safe_automatic_link(group, group["files"][0]))

    def test_single_unlabeled_ova_infers_e01_only_with_exact_curated_work(self):
        group = refine(plan("Shinmai Maou no Testament Departures",
                            ["[Group] Shinmai Maou no Testament Departures (BD 1080p).mkv"]))["groups"][0]
        row = group["files"][0]
        self.assertEqual((row["target_anidb_id"], row["episode_type"], row["episode"]),
                         (13543, "Episode", 1))
        self.assertTrue(is_safe_automatic_link(group, row))
        no_rule = refine(plan("A Completely Unknown OVA",
                              ["unknown movie without ep.mkv"]))["groups"][0]
        self.assertIsNone(no_rule["files"][0]["target_anidb_id"])

    def test_bad_season_cannot_use_first_season_crosswalk(self):
        group = refine(plan("Horimiya", ["Horimiya S02E01.mkv"]))["groups"][0]
        row = group["files"][0]
        self.assertFalse(is_safe_automatic_link(group, row))
        self.assertIsNone(row["target_anidb_id"])

    def test_generic_suffix_and_extra_policy(self):
        self.assertEqual(
            clean_release_title("[Judas] ATRI -My Dear Moments- (Season 01) [Multi-Subs]v2"),
            "ATRI -My Dear Moments- Season 01"
        )
        group = refine(plan("[Group] Horimiya [BDRip 1080p]",
                            ["Horimiya - NCOP.mkv"]))["groups"][0]
        row = group["files"][0]
        self.assertFalse(is_safe_automatic_link(group, row))


if __name__ == "__main__":
    unittest.main()
