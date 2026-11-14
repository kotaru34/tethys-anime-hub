"""Live-free end-to-end regression tests from CT2601's November 14 review."""
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from auto_fallback import keep_safe_rows
from matching import classify_episode
from shoko_reconcile import apply
from verified_tv_batch import promote_verified_tv_batch, unique_tv_work


def make_group(folder, selected, competing, filenames):
    rows = []
    for n, filename in enumerate(filenames, 1):
        path = folder + "/" + filename
        info = classify_episode(path, group=folder)
        rows.append({
            "file_id": n + 100, "path": path,
            "episode": info.number, "source_episode": None,
            "episode_type": info.category,
            "target_anidb_id": selected["anidb_id"],
            "mode": "strong_context",
        })
    return {"folder": folder, "candidates": [selected, *competing],
            "files": rows, "mode": "strong_context"}


class Stub:
    def __init__(self, aid, rows, count=12):
        self.aid, self.rows, self.count = aid, rows, count
        self.linked = []

    def local_series(self, aid):
        return {"IDs": {"AniDB": aid, "ID": 99}} if aid == self.aid else None

    def available_episodes(self, sid):
        assert sid == 99
        return {("Episode", n) for n in range(1, self.count + 1)}

    def unrecognized(self):
        return [{"ID": r["file_id"], "Locations": [{"RelativePath": r["path"]}]}
                for r in self.rows]

    def link(self, fid, sid, episode, kind):
        self.linked.append((fid, episode, kind))

    def refresh_series(self, aid):
        raise AssertionError("Complete local AniDB metadata is already present")


def promote(group, api):
    eligible = {r["file_id"] for r in group["files"]}
    plan = {"version": 2, "groups": [group]}
    number = promote_verified_tv_batch(api, plan, eligible)
    safe, rejected = keep_safe_rows(plan, eligible)
    return number, safe, rejected


class ShortAndSeasonIdentityTests(unittest.TestCase):
    def test_vcb_adjacent_technical_block_and_end_marker(self):
        folder = "Rakudai Kishi no Cavalry [BDRip 1080p]"
        for n in range(1, 13):
            path = (f"{folder}/[VCB-Studio] Rakudai Kishi no Cavalry "
                    f"[{n:02}][Ma10p_1080p][x265_flac].mkv")
            self.assertEqual(
                (classify_episode(path, group=folder).category,
                 classify_episode(path, group=folder).number),
                ("Episode", n))
        self.assertEqual(
            (classify_episode(
                "Seirei Gensouki/Seirei_Gensouki_[12_END]_[HEVC].mkv").category,
             classify_episode(
                "Seirei Gensouki/Seirei_Gensouki_[12_END]_[HEVC].mkv").number),
            ("Episode", 12))

    def test_goblin_slayer_2_roman_sequel_with_real_12_episode_inventory(self):
        folder = "Goblin Slayer 2 - AniLibria.TV [WEBRip 1080p HEVC]"
        group = make_group(
            folder,
            {"anidb_id": 16027, "title": "Goblin Slayer II",
             "season": 2, "type": "TV", "score": 1},
            [{"anidb_id": 13831, "title": "Goblin Slayer",
              "season": None, "type": "TV", "score": 0.871}],
            [f"Goblin_Slayer_2_[{n:02}]_[HEVC].mkv" for n in range(1, 13)])
        api = Stub(16027, group["files"])
        count, safe, rejected = promote(group, api)
        self.assertEqual((count, rejected), (12, 0))
        self.assertEqual(apply(api, safe, delay=0)["submitted"], 12)
        self.assertEqual(len(api.linked), 12)

    def test_kaguya_second_season_uses_full_base_title_and_verified_season(self):
        folder = ("Kaguya-sama wa Kokurasetai Tensai-tachi no Renai Zunousen 2 "
                  "- AniLibria.TV [WEBRip 1080p HEVC]")
        group = make_group(
            folder,
            {"anidb_id": 15207,
             "title": "Kaguya-sama wa Kokurasetai? Tensai-tachi no Renai Zunousen",
             "type": "TV", "season": 2, "score": 1},
            [{"anidb_id": 14111, "title":
              "Kaguya-sama wa Kokurasetai: Tensai-tachi no Renai Zunousen",
              "type": "TV", "season": None, "score": 0.9646}],
            [f"Kaguya-sama_wa_Kokurasetai_Tensai-tachi_no_Renai_Zunousen_2_[{n:02}]_[HEVC].mkv"
             for n in range(1, 13)])
        api = Stub(15207, group["files"])
        count, safe, rejected = promote(group, api)
        self.assertEqual((count, rejected), (12, 0))
        self.assertEqual(apply(api, safe, delay=0)["submitted"], 12)

    def test_seirei_second_season_unknown_type_but_proven_anidb_episodes(self):
        folder = "Seirei Gensouki 2 - AniLibria [WEBRip 1080p HEVC]"
        group = make_group(
            folder,
            {"anidb_id": 16962, "title": "Seirei Gensouki: Spirit Chronicles 2",
             "aliases": ["Seirei Gensouki 2"],
             "type": "Unknown", "season": 2, "score": 1},
            [{"anidb_id": 15875, "title": "Seirei Gensouki",
              "type": "TV", "season": None, "score": 0.8779}],
            [f"Seirei_Gensouki_2_[{n:02}]_[HEVC].mkv"
             for n in range(1, 13)])
        api = Stub(16962, group["files"])
        count, safe, rejected = promote(group, api)
        self.assertEqual((count, rejected), (12, 0))
        self.assertEqual(apply(api, safe, delay=0)["submitted"], 12)

    def test_dxd_unnumbered_sequel_exact_title_but_incomplete_batch_stays_review(self):
        folder = "[Snow-Raws] High School DxD Born [BDRip 1920x1080 HEVC FLAC]"
        group = make_group(
            folder,
            {"anidb_id": 10691, "title": "High School DxD Born",
             "type": "Unknown", "season": 3, "score": 1},
            [{"anidb_id": 8660, "title": "High School DxD",
              "type": "TV", "score": 0.83}],
            [f"[Snow-Raws] High School DxD BorN - {n:02} [HEVC].mkv"
             for n in range(1, 19)])
        self.assertEqual(unique_tv_work(group)["anidb_id"], 10691)
        api = Stub(10691, group["files"], count=12)
        count, _, rejected = promote(group, api)
        self.assertEqual((count, rejected), (0, 18))
        self.assertEqual(api.linked, [])

    def test_two_exact_neko_works_stay_ambiguous(self):
        folder = "Nekopara - AniLibria [WEBRip 1080p]"
        group = make_group(
            folder,
            {"anidb_id": 12622, "title": "Nekopara",
             "type": "Unknown", "score": 1},
            [{"anidb_id": 14570, "title": "Nekopara",
              "type": "Unknown", "score": 1}],
            [f"Nekopara_[{n:02}]_[HEVC].mkv" for n in range(1, 13)])
        self.assertIsNone(unique_tv_work(group))
        count, _, rejected = promote(group, Stub(14570, group["files"]))
        self.assertEqual((count, rejected), (0, 12))

    def test_source_second_season_never_selects_untagged_s1(self):
        folder = "Goblin Slayer 2 - AniLibria.TV [WEBRip 1080p HEVC]"
        group = make_group(
            folder,
            {"anidb_id": 13831, "title": "Goblin Slayer",
             "type": "TV", "score": 1},
            [],
            [f"Goblin_Slayer_2_[{n:02}]_[HEVC].mkv" for n in range(1, 13)])
        self.assertIsNone(unique_tv_work(group))


if __name__ == "__main__":
    unittest.main()
