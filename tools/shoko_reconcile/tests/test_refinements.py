"""v2.2 audit tests with synthetic filenames; never commit user library inventory."""
from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from refinements import refine, known_aliases
from shoko_reconcile import ShokoAPI, apply


def synthetic(folder, candidates, files, *, selected=None, mode="review", total=1000):
    rows = [{"file_id": idx + 1, "path": folder + "/" + filename,
             "source_episode": n, "episode": n, "episode_type": kind,
             "target_anidb_id": selected, "mode": mode, "reason": ""}
            for idx, (filename, n, kind) in enumerate(files)]
    return {"version": 2, "source_total_files_at_scan": total,
            "source_unrecognized_at_scan": len(rows), "groups": [{
            "folder": folder, "title_guess": folder, "mode": mode,
            "candidates": candidates, "selected_anidb_id": selected,
            "count": len(rows), "files": rows}]}


class RefinementTests(unittest.TestCase):
    def test_public_crosswalk_is_exact_not_substring_fuzzy(self):
        p = synthetic("Chichi wa Eiyuu [WEB-DL 1080p]", [],
            [(f"Chichi wa Eiyuu - {i:02d}.mkv", i, "Episode") for i in range(1, 13)])
        r = refine(p)
        self.assertEqual(r["metrics"]["potential_links_before_api_validation"], 12)
        self.assertEqual({f["target_anidb_id"] for f in r["groups"][0]["files"]}, {18437})
        q = synthetic("Chichi wa Eiyuu 3 [WEB-DL 1080p]", [], [("Chichi wa Eiyuu 3 - 01.mkv", 1, "Episode")])
        self.assertIsNone(refine(q)["groups"][0]["files"][0]["target_anidb_id"])

    def test_archived_go_toubun_special_2024_needs_external_release_evidence(self):
        # Actual archived v2.2 candidates: selected 17968 for ~, but the
        # release was 2024 (AniDB 18603). Never silently apply the old ID.
        name = "Go-Toubun no Hanayome~ - AniLibria.TV [WEBRip 1080p HEVC]"
        candidates = [
            {"anidb_id": 17968, "title": "Go-Toubun no Hanayome~",
             "type": "SPECIAL", "score": 1.0},
            {"anidb_id": 18603, "title": "5-toubun no Hanayome*",
             "type": "SPECIAL", "score": 0.698},
        ]
        p = synthetic(name, candidates, [("Episode_[01].mkv", 1, "Episode"),
                                         ("Episode_[02].mkv", 2, "Episode")],
                      selected=17968, mode="auto_evidence")
        rows = refine(p)["groups"][0]["files"]
        self.assertEqual([r["target_anidb_id"] for r in rows], [None, None])
        self.assertTrue(all(r["mode"] == "episode_review" for r in rows))
        self.assertIsNone(p["groups"][0]["selected_anidb_id"])

    def test_second_season_not_confused_with_first(self):
        p = synthetic("Kanojo Okarishimasu 2nd Season - AniLibria.TV [WEBRip 1080p HEVC]", [
            {"anidb_id": 15299, "title": "Kanojo, Okarishimasu", "type": "TV", "episodes": 12},
            {"anidb_id": 15743, "title": "Kanojo, Okarishimasu 2nd Season", "type": "TV", "episodes": 12}],
            [(f"S02E{i:02d}.mkv", i, "Episode") for i in range(1, 13)])
        self.assertEqual({x["target_anidb_id"] for x in refine(p)["groups"][0]["files"]}, {15743})

    def test_rezero_absolute_episode_numbers_are_offset_only_with_full_block(self):
        name = "[Judas] Re.Zero kara Hajimeru Isekai Seikatsu (Season 2 Part 2) [1080p][HEVC x265 10bit][Multi-Subs]"
        c = [{"anidb_id": 15593, "title":"Re:Zero kara Hajimeru Isekai Seikatsu 2nd Season Part 2", "type":"TV", "episodes":12}]
        p = synthetic(name, c, [(f"S02E{i:02d}.mkv", i, "Episode") for i in range(14,26)])
        r = refine(p)["groups"][0]["files"]
        self.assertEqual([x["episode"] for x in r], list(range(1,13)))
        self.assertEqual([x["source_episode"] for x in r], list(range(14,26)))
        partial = synthetic(name, c, [("S02E17.mkv",17,"Episode")])
        self.assertEqual(refine(partial)["groups"][0]["files"][0]["episode"],17)

    def test_full_cour_split_is_per_file_with_verified_part2(self):
        folder = "[Group] Tensei Shitara Slime Datta Ken S02"
        p = synthetic(folder,[
            {"anidb_id":14767,"title":"Tensei Shitara Slime Datta Ken 2nd Season","type":"TV","episodes":12},
            {"anidb_id":15456,"title":"Tensei Shitara Slime Datta Ken 2nd Season Part 2","type":"TV","episodes":12}],
            [(f"Tensura S02E{i:02d}.mkv",i,"Episode") for i in range(1,25)],
            selected=14767,mode="prior_exact_title")
        rows=refine(p)["groups"][0]["files"]
        self.assertEqual([x["target_anidb_id"] for x in rows[:12]], [14767]*12)
        self.assertEqual([x["target_anidb_id"] for x in rows[12:]], [15456]*12)
        self.assertEqual([x["episode"] for x in rows[12:]], list(range(1,13)))
        self.assertEqual(len({x["file_id"] for x in rows}),24)

    def test_standalone_ova_uses_main_episode_number_not_special_prefix(self):
        folder = "Show [OVA]"
        p=synthetic(folder, [{"anidb_id":321,"title":"Show OVA", "type":"OVA", "episodes":2}],
            [("OVA 01.mkv",1,"Special"),("OVA 02.mkv",2,"Special")],
            selected=321,mode="prior_exact_title")
        rows=refine(p)["groups"][0]["files"]
        self.assertEqual([x["episode_type"] for x in rows],["Episode","Episode"])

    def test_movie_without_episode_number_and_with_bonus(self):
        folder = "No Game No Life - Zero [BDRip 1080p x264 FLAC]"
        p=synthetic(folder, [{"anidb_id":12276,"title":"No Game No Life Zero", "type":"Unknown"}],
          [("Film.mkv",None,"Unknown"),("Bonus/Trailer.mkv",None,"Extra")],
          selected=12276,mode="prior_exact_title")
        p["groups"][0]["files"][1]["mode"]="extra"
        rows=refine(p)["groups"][0]["files"]
        self.assertEqual((rows[0]["episode"],rows[0]["episode_type"]),(1,"Movie"))
        self.assertIsNone(rows[1]["episode"])

    def test_24_5_recaps_must_not_be_falsely_recognized_as_e25(self):
        folder="Про моє переродження в слиз"
        p=synthetic(folder, [],[(f"Про моє переродження в слиз_s1_{i:02d}.mkv",i,"Episode") for i in range(1,26)])
        rows=refine(p)["groups"][0]["files"]
        self.assertEqual(sum(x.get("target_anidb_id") is not None for x in rows),24)
        self.assertIsNone(rows[-1]["target_anidb_id"])

    def test_chibi_nested_title_is_separate_work_when_catalog_confirmed(self):
        class Catalog:
            def lookup(self, query):
                return ([{"anidb_id":43210,"title":"Youjo Shenki","aliases":["Youjo Shenki"],
                          "type":"ONA","episodes":12}] if query=="Youjo Shenki" else [])
        folder="Youjo Senki (BDRip 1920x1080 x264 FLAC)"
        p=synthetic(folder,[{"anidb_id":11905,"title":"Youjo Senki", "type":"TV", "episodes":12}],
            [(f"Youjo Shenki/Youjo Shenki - {i:02d}.mkv",i,"Episode") for i in range(1,13)],
            selected=11905,mode="prior_exact_title")
        rows=refine(p,catalog=Catalog())["groups"][0]["files"]
        self.assertEqual({r["target_anidb_id"] for r in rows},{43210})
        self.assertEqual({r["mode"] for r in rows},{"nested_exact_work"})

    def test_reanalysis_idempotent(self):
        folder="Chichi wa Eiyuu [WEB-DL 1080p]"
        p=synthetic(folder,[],[("Chichi wa Eiyuu - 01.mkv",1,"Episode")])
        first=refine(deepcopy(p))
        second=refine(deepcopy(first))
        self.assertEqual(first["metrics"],second["metrics"])


if __name__ == "__main__":
    unittest.main()
