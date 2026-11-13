"""Ensure an identified work with an unnumbered release remains for episode review."""
import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from shoko_reconcile import analyze_report, metrics


class UnnumberedReleaseTests(unittest.TestCase):
    def _report(self, file_name):
        folder = "Example Standalone Work"
        return analyze_report({
            "version": 1,
            "total_files_at_scan": 100,
            "total_unrecognized_at_scan": 1,
            "groups": [{
                "folder": folder,
                "candidates": [{
                    "anidb_id": 12345,
                    "title": folder,
                    "type": "Unknown",
                    "shoko_id": None,
                }],
                "files": [{
                    "file_id": 789,
                    "path": folder + "/" + file_name,
                }],
            }],
        })

    def test_unnumbered_series_identity_preserves_episode_review(self):
        report = self._report("Example Standalone Work.mkv")
        group = report["groups"][0]
        row = group["files"][0]
        self.assertEqual(group["selected_anidb_id"], 12345)
        self.assertEqual(row["target_anidb_id"], 12345)
        self.assertIsNone(row["episode"])
        self.assertEqual(row["mode"], "episode_review")
        self.assertIn("episode identity is unverified", row["reason"])
        self.assertEqual(metrics(report)["potential_links_before_api_validation"], 0)

    def test_numbered_episode_still_autolinks_in_plan(self):
        report = self._report("Example Standalone Work - 01.mkv")
        row = report["groups"][0]["files"][0]
        self.assertEqual(row["target_anidb_id"], 12345)
        self.assertEqual(row["episode"], 1)
        self.assertNotEqual(row["mode"], "episode_review")
        self.assertEqual(metrics(report)["potential_links_before_api_validation"], 1)


if __name__ == "__main__":
    unittest.main()
