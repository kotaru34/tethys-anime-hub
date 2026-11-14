"""Unique exact-title safety and public-crosswalk rescue regression tests.

Use synthetic release paths. No Shoko API calls or media mutations.
"""
from __future__ import annotations

from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from matching import classify_episode
from refinements import refine, unique_exact_work_candidate
from auto_fallback import is_safe_automatic_link, auto_link_rejection_reason


def candidate(aid, name, score, *, season=None, kind="TV", matched_alias=None):
    return {"anidb_id": aid, "title": name, "score": score,
            "season": season, "type": kind,
            "matched_alias": matched_alias or name}


def group(folder, candidates, *, name="Example - 01.mkv",
          selected=None, mode="auto_evidence", extra=False):
    path = f"{folder}/{name}"
    parsed = classify_episode(path, group=folder)
    if extra:
        parsed = classify_episode(f"{folder}/NCOP.mkv", group=folder)
        path = f"{folder}/NCOP.mkv"
    row = {"file_id": 1, "path": path, "episode": parsed.number,
           "episode_type": parsed.category, "source_episode": None,
           "target_anidb_id": selected, "mode": "extra" if extra else mode,
           "reason": "title + context matched"}
    return {"version": 2, "source_total_files_at_scan": 3000,
            "source_unrecognized_at_scan": 1, "groups": [{
                "folder": folder, "title_guess": folder,
                "selected_anidb_id": selected, "mode": mode,
                "reason": "title + context matched",
                "candidates": candidates, "files": [row], "count": 1,
            }]}


class ExactIdentityTests(unittest.TestCase):
    def test_curated_exact_alias_upgrades_already_selected_auto_evidence(self):
        examples = [
            (
                "Maou Gakuin no Futekigousha - AniLibria.TV [WEBRip 1080p HEVC]",
                [candidate(15131,
                           "Maou Gakuin no Futekigousha: Shijou Saikyou no Maou no Shiso, Tensei shite Shison-tachi no Gakkou e Kayou",
                           1.0),
                 candidate(16101, "Maou Gakuin no Futekigousha II", 0.93, season=2)],
                "Maou_Gakuin_no_Futekigousha_[01].mkv", 15131
            ),
            (
                "[Group] Yofukashi no Uta [WEB-DL 1080p AVC]",
                [candidate(16971, "Call of the Night", 1.0),
                 candidate(18531, "Yofukashi no Uta Season 2", 0.88, season=2)],
                "Yofukashi no Uta 01.mkv", 16971
            )
        ]
        for folder, candidates, name, aid in examples:
            with self.subTest(folder=folder):
                data = group(folder, candidates, name=name, selected=aid)
                resolved = refine(data)["groups"][0]
                row = resolved["files"][0]
                self.assertEqual(row["target_anidb_id"], aid)
                self.assertEqual(row["mode"], "public_crosswalk")
                self.assertIsNone(auto_link_rejection_reason(resolved, row))

    def test_unique_full_title_is_good_even_when_fuzzy_margin_small(self):
        examples = [
            ("To LOVE-Ru", 6012, "To LOVE-Ru", "To LOVE-Ru Darkness"),
            ("High School DxD Born", 1234, "High School DxD Born", "High School DxD New"),
            ("Kamonohashi Ron no Kindan Suiri", 4567,
             "Kamonohashi Ron no Kindan Suiri", "Kamonohashi Ron no Kindan Suiri 2nd Season"),
            ("Akatsuki no Yona", 5678, "Akatsuki no Yona", "Akatsuki no Yona OVA"),
        ]
        for release, aid, title, second in examples:
            with self.subTest(release=release):
                folder = f"{release} - AniLibria [WEBRip 1080p HEVC]"
                data = group(folder, [
                    candidate(aid, title, 1.0),
                    candidate(aid+100, second, 0.92, season=2)],
                    name=f"{release} - 01.mkv", selected=aid)
                resolved = refine(data)["groups"][0]
                row = resolved["files"][0]
                self.assertEqual(row["mode"], "exact_work_title")
                self.assertEqual(row["target_anidb_id"], aid)
                self.assertTrue(is_safe_automatic_link(resolved, row))

    def test_exact_alias_collision_between_two_work_ids_stays_manual(self):
        folder = "Example"
        data = group(folder, [
            candidate(1, "Example", 1.0),
            candidate(2, "Example 2", 0.99,
                      matched_alias="Example")],
            selected=1)
        resolved = refine(data)["groups"][0]
        self.assertIsNone(unique_exact_work_candidate(resolved))
        self.assertNotEqual(resolved["files"][0]["mode"], "exact_work_title")
        self.assertFalse(is_safe_automatic_link(resolved, resolved["files"][0]))

    def test_season_and_cour_must_not_be_erased_by_exact_base_alias(self):
        a = group("Example S2", [
            candidate(1, "Example", 1.0, season=1, matched_alias="Example S2"),
            candidate(2, "Example II", 0.99, season=2)],
            selected=1, name="Example S02E01.mkv")
        self.assertIsNone(unique_exact_work_candidate(a["groups"][0]))

        b = group("Example S2 Part 2", [
            candidate(2, "Example S2 Part 2", 1.0, season=2),
            candidate(1, "Example S2", 0.99, season=2,
                      matched_alias="Example S2 Part 2")],
            selected=2, name="Example S02E01.mkv")
        self.assertEqual(unique_exact_work_candidate(b["groups"][0])["anidb_id"], 2)

    def test_extra_material_never_becomes_normal_episode(self):
        data = group("To LOVE-Ru", [candidate(6012, "To LOVE-Ru", 1.0)],
                     selected=6012, extra=True)
        resolved = refine(data)["groups"][0]
        row = resolved["files"][0]
        self.assertEqual(row["mode"], "extra")
        self.assertFalse(is_safe_automatic_link(resolved, row))

    def test_invalid_exact_mode_is_rechecked_in_auto_policy(self):
        fake = group("Example", [
            candidate(1, "Example", 1.0),
            candidate(2, "Example 2", 0.99, matched_alias="Example")],
            selected=1)
        g = fake["groups"][0]
        row = g["files"][0]
        row["mode"] = "exact_work_title"
        self.assertEqual(auto_link_rejection_reason(g, row),
                         "exact_work_title_not_unique_or_changed")


if __name__ == "__main__":
    unittest.main()
