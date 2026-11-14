"""Safe complete-TV batch proof, using only synthetic Shoko API responses."""
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from auto_fallback import keep_safe_rows
from shoko_reconcile import apply
from verified_tv_batch import (promote_verified_tv_batch, tv_batch_proof,
                               unique_tv_work)

FOLDER = "Konoyo no Hate de Koi o Utau Shoujo YU-NO - AniLibria.TV [HDTVRip 1080p HEVC]"
TITLE = "Kono Yo no Hate de Koi o Utau Shoujo YU-NO"


def plan(count=26):
    group = {
        "folder": FOLDER,
        "candidates": [
            {"anidb_id": 12345, "title": TITLE, "type": "TV",
             "score": 0.95, "season": None},
            {"anidb_id": 77777, "title": "Kono Yo no Hate de Koi o Utau Shoujo YU-NO 2nd Season",
             "type": "TV", "score": 0.93, "season": 2},
        ],
        "files": [
            {"file_id": i + 100, "path": f"{FOLDER}/YU-NO - {i:02}.mkv",
             "episode": i, "source_episode": i, "episode_type": "Episode",
             "target_anidb_id": 12345, "mode": "strong_context"}
            for i in range(1, count + 1)
        ],
    }
    return {"version": 2, "groups": [group]}


class FakeShoko:
    def __init__(self, count=26):
        self.count = count
        self.linked = []
        self.calls = 0

    def local_series(self, aid):
        self.calls += 1
        return {"IDs": {"AniDB": aid, "ID": 55}} if aid == 12345 else None

    def available_episodes(self, sid):
        assert sid == 55
        return {("Episode", i) for i in range(1, self.count + 1)}

    def unrecognized(self):
        return [{"ID": n + 100, "Locations": [{"RelativePath": f"{FOLDER}/YU-NO - {n:02}.mkv"}]}
                for n in range(1, 27)]

    def link(self, fid, sid, ep, kind):
        self.linked.append((fid, sid, ep, kind))

    def refresh_series(self, aid):
        raise AssertionError("This proof never queues global metadata refresh")


class CompleteTvBatchTests(unittest.TestCase):
    def test_full_romaji_identity_and_exact_anidb_episode_inventory_links(self):
        api = FakeShoko()
        p = plan()
        eligible = {r["file_id"] for r in p["groups"][0]["files"]}
        self.assertEqual(unique_tv_work(p["groups"][0])["anidb_id"], 12345)
        diagnostics = {}
        self.assertEqual(promote_verified_tv_batch(api, p, eligible,
                                                    diagnostics=diagnostics), 26)
        self.assertEqual(diagnostics["verified_tv_groups"], 1)
        safe, rejected = keep_safe_rows(p, eligible)
        self.assertEqual(rejected, 0)
        self.assertTrue(all(r["mode"] == "verified_tv_batch"
                            for r in safe["groups"][0]["files"]))
        result = apply(api, safe, delay=0)
        self.assertEqual(result["submitted"], 26)
        self.assertEqual(len(api.linked), 26)
        self.assertEqual(api.linked[0], (101, 55, 1, "Episode"))
        self.assertEqual(api.linked[-1], (126, 55, 26, "Episode"))

    def test_incomplete_batch_does_not_substitute_fuzzy_guess(self):
        api = FakeShoko()
        p = plan(count=25)
        eligible = {r["file_id"] for r in p["groups"][0]["files"]}
        self.assertEqual(promote_verified_tv_batch(api, p, eligible), 0)
        self.assertTrue(all(r["mode"] == "strong_context"
                            for r in p["groups"][0]["files"]))

    def test_nonexistent_anidb_episode_blocks_entire_batch(self):
        api = FakeShoko(count=25)
        p = plan()
        eligible = {r["file_id"] for r in p["groups"][0]["files"]}
        self.assertEqual(promote_verified_tv_batch(api, p, eligible), 0)

    def test_ova_in_same_folder_is_not_promoted_with_tv(self):
        api = FakeShoko()
        p = plan()
        p["groups"][0]["files"].append({
            "file_id": 3321, "path": f"{FOLDER}/YU-NO - 27 (OVA 1).mp4",
            "source_episode": 1, "episode": 1, "episode_type": "Special",
            "target_anidb_id": None, "mode": "episode_review"})
        eligible = {r["file_id"] for r in p["groups"][0]["files"]}
        self.assertEqual(promote_verified_tv_batch(api, p, eligible), 26)
        self.assertEqual(p["groups"][0]["files"][-1]["mode"], "episode_review")
        safe, rejected = keep_safe_rows(p, eligible)
        self.assertEqual(rejected, 1)
        self.assertEqual(len(safe["groups"][0]["files"]), 26)

    def test_two_exact_works_are_ambiguous(self):
        p = plan()
        p["groups"][0]["candidates"].append({
            "anidb_id": 99999, "title": TITLE, "type": "TV", "score": 0.97})
        self.assertIsNone(unique_tv_work(p["groups"][0]))
        eligible = {r["file_id"] for r in p["groups"][0]["files"]}
        self.assertEqual(promote_verified_tv_batch(FakeShoko(), p, eligible), 0)

    def test_edited_plan_and_expired_metadata_are_rejected_at_apply(self):
        api = FakeShoko()
        p = plan()
        eligible = {r["file_id"] for r in p["groups"][0]["files"]}
        self.assertEqual(promote_verified_tv_batch(api, p, eligible), 26)
        safe, _ = keep_safe_rows(p, eligible)
        safe["groups"][0]["candidates"].append({
            "anidb_id": 87654, "title": TITLE, "type": "TV"})
        result = apply(api, safe, delay=0)
        self.assertEqual(result["submitted"], 0)
        self.assertEqual(result["deferred_by_reason"].get(
            "verified_tv_batch_live_proof_missing"), 26)
        self.assertEqual(api.linked, [])

    def test_sequel_root_or_unnumbered_work_not_accepted(self):
        p = plan()
        p["groups"][0]["folder"] = "Kono Yo no Hate de Koi o Utau Shoujo YU-NO"
        p["groups"][0]["candidates"] = [{
            "anidb_id": 12345, "title": TITLE + " 2nd Season",
            "type": "TV", "season": 2}]
        self.assertIsNone(unique_tv_work(p["groups"][0]))


if __name__ == "__main__":
    unittest.main()
