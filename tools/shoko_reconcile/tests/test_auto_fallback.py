"""Conservative automatic fallback regression tests (synthetic media only)."""
from __future__ import annotations

from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from auto_fallback import is_safe_automatic_link, auto_link_rejection_reason, keep_safe_rows, eligible_final_files, review_diagnostics


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

    def test_strong_context_requires_same_strict_candidate_evidence_as_auto_evidence(self):
        strong = self.row(mode="strong_context")
        strong_group = self.group([strong], [
            {"anidb_id": 17968, "score": 0.99},
            {"anidb_id": 14247, "score": 0.78},
        ])
        self.assertTrue(is_safe_automatic_link(strong_group, strong))
        strong_group["candidates"][0]["score"] = 0.97
        self.assertFalse(is_safe_automatic_link(strong_group, strong))
        strong_group["candidates"][0]["score"] = 0.99
        strong_group["candidates"][1]["score"] = 0.85
        self.assertFalse(is_safe_automatic_link(strong_group, strong))

    def test_strong_context_never_ignores_season_or_episode_offsets(self):
        group = self.group([self.row(mode="strong_context")])
        wrong_season = self.row(mode="strong_context")
        wrong_season["path"] = "Example/Example S02E01.mkv"
        self.assertFalse(is_safe_automatic_link(group, wrong_season))
        shifted = self.row(mode="strong_context")
        shifted["source_episode"] = 13
        self.assertFalse(is_safe_automatic_link(group, shifted))
        unknown_episode = self.row(mode="strong_context", episode=None)
        self.assertFalse(is_safe_automatic_link(group, unknown_episode))

    def test_review_diagnostics_count_reasons_and_group_identity(self):
        good = self.row(fid=1, mode="strong_context")
        ambiguous = self.row(fid=2, mode="strong_context")
        unnumbered = self.row(fid=3, mode="episode_review", episode=None)
        good_group = self.group([good], [
            {"anidb_id": 17968, "score": 1.0},
            {"anidb_id": 14247, "score": 0.6},
        ])
        bad_group = self.group([ambiguous, unnumbered], [
            {"anidb_id": 17968, "score": 0.96},
            {"anidb_id": 14247, "score": 0.90},
        ])
        for row in bad_group["files"]:
            row["reason"] = "ambiguous new release"
        plan = {"version": 2, "groups": [good_group, bad_group]}
        report = review_diagnostics(plan, {1, 2, 3})
        self.assertEqual(report["review_by_mode"], {
            "episode_review": 1, "strong_context": 1
        })
        self.assertEqual(report["review_by_reason"], {"ambiguous new release": 2})
        self.assertEqual(report["review_groups_total"], 1)
        self.assertEqual(report["review_top_groups"][0]["files"], 2)

    def test_specific_safety_gate_reasons_for_ranked_candidates(self):
        row = self.row()
        group = self.group([row])
        self.assertIsNone(auto_link_rejection_reason(group, row))

        group["candidates"][0]["score"] = 0.97
        self.assertEqual(
            auto_link_rejection_reason(group, row),
            "selected_candidate_score_below_0.98",
        )
        group["candidates"][0]["score"] = 1.0
        group["candidates"][1]["score"] = 0.85
        self.assertEqual(
            auto_link_rejection_reason(group, row),
            "competing_candidate_within_0.18",
        )
        group["candidates"][1]["score"] = 0.75
        shifted = {**row, "source_episode": 14}
        self.assertEqual(
            auto_link_rejection_reason(group, shifted),
            "episode_number_shift_requires_review",
        )
        unnumbered = {**row, "episode": None}
        self.assertEqual(
            auto_link_rejection_reason(group, unnumbered),
            "missing_work_or_episode_identity",
        )

    def test_review_diagnostics_explain_real_gate_not_title_reason(self):
        row = self.row()
        group = self.group([row], [
            {"anidb_id": 17968, "score": 0.99},
            {"anidb_id": 14247, "score": 0.94},
        ])
        row["reason"] = "title + context matched"
        plan = {"version": 2, "groups": [group]}
        result = review_diagnostics(plan, {1})
        self.assertEqual(result["review_by_mode"], {"auto_evidence": 1})
        self.assertEqual(result["review_by_gate"],
                         {"competing_candidate_within_0.18": 1})
        self.assertEqual(result["review_by_reason"],
                         {"title + context matched": 1})
        self.assertFalse(is_safe_automatic_link(group, row))

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

    def test_qbittorrent_partial_files_are_excluded_immediately(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "Episode.mkv.!qB").write_bytes(b"partial")
            (root / "Episode2.mkv.qb!").write_bytes(b"partial")
            (root / "Episode3.mkv").write_bytes(b"completed")
            unknown = [
                {"ID": 1, "Locations": [{"RelativePath": "Episode.mkv.!qB"}]},
                {"ID": 2, "Locations": [{"RelativePath": "Episode2.mkv.qb!"}]},
                {"ID": 3, "Locations": [{"RelativePath": "Episode3.mkv"}]},
            ]
            self.assertEqual(eligible_final_files(unknown, media_root=root), {3})

    def test_final_file_is_eligible_on_first_event_without_age_wait(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            folder = root / "Example"
            folder.mkdir()
            file = folder / "01.mkv"
            file.write_bytes(b"data")
            unknown = [{"ID": 42, "Locations": [{"RelativePath": "Example/01.mkv"}]}]
            # The first pass must include even a just-created final file.
            self.assertEqual(eligible_final_files(unknown, media_root=root), {42})
            file.write_bytes(b"more data")
            self.assertEqual(eligible_final_files(unknown, media_root=root), {42})

    def test_empty_missing_and_escaped_paths_cannot_be_linked(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "empty.mkv").touch()
            outside = Path(tmp).parent / ("outside-" + root.name + ".mkv")
            outside.write_bytes(b"data")
            try:
                (root / "out.mkv").symlink_to(outside)
                unknown = [
                    {"ID": 1, "Locations": [{"RelativePath": "../outside.mkv"}]},
                    {"ID": 2, "Locations": [{"RelativePath": "empty.mkv"}]},
                    {"ID": 3, "Locations": [{"RelativePath": "does-not-exist.mkv"}]},
                    {"ID": 4, "Locations": [{"RelativePath": "out.mkv"}]},
                ]
                self.assertEqual(eligible_final_files(unknown, media_root=root), set())
            finally:
                outside.unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main()
