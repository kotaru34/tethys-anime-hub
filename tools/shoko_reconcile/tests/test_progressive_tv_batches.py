"""Safety regressions for ongoing series and mixed TV/special torrent releases."""
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from auto_fallback import auto_link_rejection_reason, keep_safe_rows
from matching import classify_episode
from refinements import refine
from shoko_reconcile import apply
from verified_tv_batch import promote_verified_tv_batch, tv_batch_proof


class InMemoryShoko:
    def __init__(self, rows, aid, length):
        self.rows = rows
        self.aid = aid
        self.length = length
        self.linked = []

    def local_series(self, aid):
        return {"IDs": {"ID": 777, "AniDB": aid}} if aid == self.aid else None

    def available_episodes(self, sid):
        assert sid == 777
        return {("Episode", n) for n in range(1, self.length + 1)}

    def unrecognized(self):
        return [{"ID": r["file_id"], "Locations": [
            {"RelativePath": r["path"]}]} for r in self.rows]

    def link(self, fid, sid, episode, kind):
        self.linked.append((fid, sid, episode, kind))

    def refresh_series(self, aid):
        raise AssertionError("Available AniDB work must never refresh")


def group(folder, title, aid, length, *, season=None, extras=(), filenames=None):
    files = []
    filenames = filenames or [f"{title} - {n:02}.mkv"
                              for n in range(1, length + 1)]
    for idx, filename in enumerate([*filenames, *extras], 1):
        path = f"{folder}/{filename}"
        info = classify_episode(path, group=folder)
        files.append({"file_id": 500 + idx, "path": path,
                      "episode_type": info.category, "episode": info.number,
                      "source_episode": None, "mode": "strong_context",
                      "target_anidb_id": aid if info.category == "Episode" else None})
    g = {"folder": folder, "candidates": [
        {"anidb_id": aid, "title": title, "type": "Unknown",
         "season": season, "score": 1.0}],
         "files": files}
    return {"version": 2, "groups": [g]}


class ProgressiveTvBatchTests(unittest.TestCase):
    def test_twelve_main_dxd_episodes_and_explicit_specials_in_one_folder(self):
        folder = "[Snow-Raws] High School DxD Born [BDRip 1920x1080 HEVC FLAC]"
        plan = group(folder, "High School DxD Born", 10691, 12,
                     season=3, extras=[
                         "Bonus/[Snow-Raws] High School DxD Born NCOP.mkv",
                         "Bonus/[Snow-Raws] High School DxD Born NCED.mkv",
                         "Specials/High School DxD Born OVA 01.mkv",
                         "Specials/High School DxD Born OVA 02.mkv",
                     ])
        rows = plan["groups"][0]["files"]
        eligible = {r["file_id"] for r in rows}
        api = InMemoryShoko(rows, 10691, 12)
        diagnostics = {}
        self.assertEqual(promote_verified_tv_batch(
            api, plan, eligible, diagnostics=diagnostics), 12)
        self.assertEqual(diagnostics["verified_tv_groups"], 1)
        self.assertEqual([r["mode"] for r in rows[:12]], ["verified_tv_batch"] * 12)
        self.assertEqual([r["mode"] for r in rows[12:]], ["strong_context"] * 4)
        safe, rejected = keep_safe_rows(plan, eligible)
        self.assertEqual((rejected, len(safe["groups"][0]["files"])), (4, 12))
        self.assertEqual(apply(api, safe, delay=0)["submitted"], 12)
        self.assertEqual(len(api.linked), 12)
        self.assertEqual({entry[3] for entry in api.linked}, {"Episode"})

    def test_reject_unlabelled_13th_main_file_even_with_exact_work(self):
        folder = "[Snow-Raws] High School DxD Born [BDRip 1920x1080 HEVC FLAC]"
        plan = group(folder, "High School DxD Born", 10691, 13, season=3)
        api = InMemoryShoko(plan["groups"][0]["files"], 10691, 12)
        diagnostics = {}
        eligible = {r["file_id"] for r in plan["groups"][0]["files"]}
        self.assertEqual(promote_verified_tv_batch(
            api, plan, eligible, diagnostics=diagnostics), 0)
        self.assertEqual(diagnostics["proof_gate_reasons"],
                         {"episode_inventory_mismatch": 1})

    def test_duplicate_normal_episode_identity_blocks_every_link(self):
        folder = "[Snow-Raws] High School DxD New [BDRip 1920x1080 HEVC FLAC]"
        filenames = [f"High School DxD New - {n:02}.mkv"
                     for n in range(1, 13)]
        filenames.append("High School DxD New - 01 [other video version].mkv")
        plan = group(folder, "High School DxD New", 9409, 13,
                     season=2, filenames=filenames)
        api = InMemoryShoko(plan["groups"][0]["files"], 9409, 12)
        diagnostics = {}
        eligible = {r["file_id"] for r in plan["groups"][0]["files"]}
        self.assertEqual(promote_verified_tv_batch(
            api, plan, eligible, diagnostics=diagnostics), 0)
        self.assertEqual(diagnostics["proof_gate_reasons"],
                         {"duplicate_main_episode_number": 1})

    def test_nested_unclassified_episodes_cannot_join_main_season(self):
        folder = "High School DxD Born"
        plan = group(folder, "High School DxD Born", 10691, 12,
                     season=3, extras=["Nested/High School DxD Born - 01.mkv"])
        api = InMemoryShoko(plan["groups"][0]["files"], 10691, 12)
        eligible = {r["file_id"] for r in plan["groups"][0]["files"]}
        failure = []
        self.assertIsNone(tv_batch_proof(
            api, plan["groups"][0], eligible=eligible, failure=failure))
        self.assertEqual(failure, ["nested_unclassified_or_tv_file"])

    def test_ongoing_seven_episode_verified_prefix_of_twelve(self):
        folder = "Goblin Slayer 2 - AniLibria.TV [WEBRip 1080p HEVC]"
        plan = group(folder, "Goblin Slayer II", 16027, 7, season=2,
                     filenames=[f"Goblin_Slayer_2_[{n:02}]_[HEVC].mkv"
                                for n in range(1, 8)])
        api = InMemoryShoko(plan["groups"][0]["files"], 16027, 12)
        eligible = {r["file_id"] for r in plan["groups"][0]["files"]}
        self.assertEqual(promote_verified_tv_batch(api, plan, eligible), 7)
        safe, rejected = keep_safe_rows(plan, eligible)
        self.assertEqual(rejected, 0)
        self.assertEqual(apply(api, safe, delay=0)["submitted"], 7)

    def test_sword_season_two_curated_alias_is_season_safe_even_while_airing(self):
        folder = ("Tensei shitara Ken Deshita 2nd Season "
                  "- AniLiberty [WEB-DL 1080p HEVC]")
        files = [
            {"file_id": 700 + n,
             "path": f"{folder}/Tensei_shitara_Ken_Deshita_2nd_Season_[{n:02}]_[HEVC].mkv",
             "episode_type": "Episode", "episode": n,
             "source_episode": None, "mode": "review",
             "target_anidb_id": None}
            for n in range(1, 8)]
        g = {"folder": folder, "files": files, "candidates": [
            {"anidb_id": 17789, "title": "Reincarnated as a Sword II",
             "type": "Unknown", "season": 2, "score": 1.0},
            {"anidb_id": 14767,
             "title": "Tensei Shitara Slime Datta Ken (2021)",
             "type": "TV", "season": 2, "score": 0.8217}],
             "mode": "review"}
        revised = refine({"version": 2, "groups": [g]})["groups"][0]
        self.assertEqual({r["mode"] for r in revised["files"]},
                         {"public_crosswalk"})
        self.assertEqual({r["target_anidb_id"] for r in revised["files"]},
                         {17789})
        self.assertTrue(all(auto_link_rejection_reason(revised, r) is None
                            for r in revised["files"]))
        api = InMemoryShoko(revised["files"], 17789, 12)
        safe, rejected = keep_safe_rows({"version": 2, "groups": [revised]},
                                        {r["file_id"] for r in revised["files"]})
        self.assertEqual(rejected, 0)
        self.assertEqual(apply(api, safe, delay=0)["submitted"], 7)


if __name__ == "__main__":
    unittest.main()
