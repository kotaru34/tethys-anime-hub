"""Tests for read-only local review-plan inspector."""
import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from inspect_review import report


class ReviewInspectorTests(unittest.TestCase):
    def test_report_has_specific_gate_candidate_and_episode(self):
        plan = {
            "version": 2,
            "groups": [{
                "folder": "Example Release",
                "reason": "title + context matched",
                "candidates": [
                    {"anidb_id": 123, "title": "Example", "score": 0.99,
                     "type": "TV", "season": 1},
                    {"anidb_id": 456, "title": "Example II", "score": 0.94,
                     "type": "TV", "season": 2},
                ],
                "files": [{
                    "file_id": 10,
                    "path": "Example Release/Episode 01.mkv",
                    "target_anidb_id": 123,
                    "episode_type": "Episode", "episode": 1,
                    "source_episode": 1,
                    "mode": "auto_evidence",
                    "reason": "title + context matched",
                }],
            }],
        }
        result = report(plan)
        self.assertIn("competing_candidate_within_0.18", result)
        self.assertIn("AniDB=123", result)
        self.assertIn("AniDB=456", result)
        self.assertIn("file=10", result)
        self.assertIn("Example Release", result)
        self.assertNotIn("APPROVED", result)


if __name__ == "__main__":
    unittest.main()
