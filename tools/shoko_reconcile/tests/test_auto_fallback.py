"""Conservative automatic fallback regression tests (synthetic media only)."""
from __future__ import annotations

from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from auto_fallback import is_safe_automatic_link, keep_safe_rows, stable_unknowns, queue_is_busy


class AutoFallbackTests(unittest.TestCase):
    def row(self, fid=1, aid=17968, episode=1, mode="auto_evidence", kind="Episode"):
        return {"file_id": fid, "target_anidb_id": aid,
                "source_episode": episode, "episode": episode,
                "episode_type": kind, "mode": mode}

    def group(self, rows, candidates=None):
        return {"folder": "Example", "files": rows, "candidates": candidates or [
            {"anidb_id": 17968, "score": 1.0},
            {"anidb_id": 14247, "score": 0.75},
        ]}

    def test_two_releases_of_one_episode_are_not_automatically_called_wrong(self):
        # Different encodes may correctly point at the SAME episode.
        rows = [self.row(1), self.row(2)]
        plan = {"version": 2, "groups": [self.group(rows)]}
        safe, review = keep_safe_rows(plan, {1, 2})
        self.assertEqual(review, 0)
        self.assertEqual(len(safe["groups"][0]["files"]), 2)

    def test_unverified_other_category_cannot_be_automatically_linked(self):
        row = self.row(100, 18603, 1, mode="public_crosswalk", kind="Other")
        self.assertFalse(is_safe_automatic_link(self.group([row]), row))

    def test_near_tie_between_sequel_and_base_is_not_auto_linked(self):
        row = self.row()
        group = self.group([row], [
            {"anidb_id": 17968, "score": 1.0},
            {"anidb_id": 14247, "score": 0.94},
        ])
        self.assertFalse(is_safe_automatic_link(group, row))

    def test_exact_verified_release_is_permitted_without_general_ova_veto(self):
        # Verified series identity is supplied by an exact release-specific
        # publisher crosswalk rather than a similarity score.
        for fid in (778, 779):
            row = self.row(fid, 18603, 1, mode="approved_release", kind="Other")
            self.assertTrue(is_safe_automatic_link(
                {"folder": "Go-Toubun no Hanayome~ - AniLibria.TV [WEBRip 1080p HEVC]",
                 "candidates": []}, row))
        row = self.row(417, 17968, 1, mode="auto_evidence")
        group = {"folder": "5-toubun no Hanayome [OVA] - AniLiberty [WEBRip 1080p HEVC]",
                 "candidates": [{"anidb_id": 17968, "score": 1.0},
                                {"anidb_id": 18603, "score": 0.7789}]}
        self.assertTrue(is_safe_automatic_link(group, row))

    def test_fuzzy_and_trailer_are_manual(self):
        self.assertFalse(is_safe_automatic_link(self.group([]), self.row(mode="review")))
        self.assertFalse(is_safe_automatic_link(self.group([]), self.row(kind="Trailer")))

    def test_cour_number_shift_requires_manual_review(self):
        row = self.row(mode="public_crosswalk")
        row["source_episode"] = 13
        row["episode"] = 1
        self.assertFalse(is_safe_automatic_link(self.group([]), row))

    def test_shoko_jobs_must_finish_before_fallback(self):
        class QueueAPI:
            def __init__(self, status): self.status = status
            def request(self, method, path):
                self.last_call = (method, path)
                return self.status
        active = QueueAPI({"TotalCount": 1, "WaitingCount": 0,
                           "BlockedCount": 0, "CurrentlyExecuting": [{"Type": "Hash"}]})
        self.assertTrue(queue_is_busy(active))
        self.assertEqual(active.last_call, ("GET", "/Queue"))
        idle = QueueAPI({"TotalCount": 0, "WaitingCount": 0,
                         "BlockedCount": 0, "CurrentlyExecuting": []})
        self.assertFalse(queue_is_busy(idle))
        blocked = QueueAPI({"TotalCount": 0, "WaitingCount": 0,
                            "BlockedCount": 2, "CurrentlyExecuting": []})
        self.assertTrue(queue_is_busy(blocked))
        with self.assertRaises(RuntimeError):
            queue_is_busy(QueueAPI(None))

    def test_repeated_stable_file_is_eligible_only_after_age(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            folder = root / "Example"
            folder.mkdir()
            file = folder / "01.mkv"
            file.write_bytes(b"data")
            now = file.stat().st_mtime + 1000
            unknown = [{"ID": 42, "Locations": [{"RelativePath": "Example/01.mkv"}]}]
            state, eligible = stable_unknowns(unknown, {}, now=now, media_root=root, minimum_age=900)
            self.assertEqual(eligible, set())
            _, eligible = stable_unknowns(unknown, state, now=now + 901, media_root=root, minimum_age=900)
            self.assertEqual(eligible, {42})
            file.write_bytes(b"more data")
            _, eligible = stable_unknowns(unknown, state, now=now + 902, media_root=root, minimum_age=900)
            self.assertEqual(eligible, set())

    def test_path_escape_is_never_eligible(self):
        with tempfile.TemporaryDirectory() as tmp:
            unknown = [{"ID": 1, "Locations": [{"RelativePath": "../outside.mkv"}]}]
            state, eligible = stable_unknowns(unknown, {}, now=10000, media_root=tmp, minimum_age=60)
            self.assertEqual(state, {})
            self.assertEqual(eligible, set())


if __name__ == "__main__":
    unittest.main()
