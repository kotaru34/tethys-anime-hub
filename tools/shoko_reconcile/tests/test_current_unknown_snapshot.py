"""Read-only current unknown inventory and optional prior-XRef audit."""
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from current_unknown_snapshot import (
    BASELINE_IDS, NEXT19, audit_prior_next19, snapshot, write_private,
)


class FakeAPI:
    def __init__(self, total=48, return_count=None):
        self.calls = []
        self.total = total
        self.known = sorted(BASELINE_IDS)[:24]
        self.new = list(range(3501, 3525))
        self.files = [
            {"ID": fid, "Locations": [{"RelativePath": f"Older Show/Older Show - {fid}.mkv"}]}
            for fid in self.known
        ] + [
            {"ID": fid,
             "Locations": [{"RelativePath": f"Date a Live IV/Date a Live IV - {i:02d}.mkv"}]}
            for i, fid in enumerate(self.new, start=1)
        ]
        if return_count is not None:
            self.files = self.files[:return_count]
        self.fail_file = None

    def request(self, method, path, params=None, body=None):
        self.calls.append((method, path, params))
        assert method == "GET" and body is None
        if path == "/File":
            assert params == {"include_only": "Unrecognized", "pageSize": 100, "page": 1}
            return {"List": self.files, "Total": self.total}
        if path.startswith("/File/"):
            fid = int(path.split("/")[-1])
            if fid == self.fail_file:
                raise RuntimeError("404 File not found")
            assert params == {"includeXRefs": "true"}
            return {
                "ID": fid, "IDs": {"ID": fid},
                "XRefs": [{"SeriesID": 268, "EpisodeID": 225607}],
                "Locations": [{"RelativePath": "Nekopara - AniLibria [WEBRip 1080p]/Nekopara_[01].mkv"}]
            }
        raise AssertionError("Unexpected API request")

    def unrecognized(self):
        raise AssertionError("Must use exactly one bounded Shoko GET")

    def link(self, *args, **kwargs):
        raise AssertionError("No Shoko writes")

    def refresh_series(self, *args, **kwargs):
        raise AssertionError("No Shoko metadata jobs")


class CurrentUnknownSnapshotTests(unittest.TestCase):
    def test_frozen_baseline_58(self):
        self.assertEqual(len(BASELINE_IDS), 58)
        self.assertIn(2486, BASELINE_IDS)
        self.assertIn(3337, BASELINE_IDS)

    def test_exactly_one_read_only_snapshot_and_both_cohorts(self):
        api = FakeAPI()
        result = snapshot(api)
        self.assertEqual(result["total_unrecognized"], 48)
        self.assertEqual(result["cohorts"], {"original_58": 24,
                                           "new_since_original_58": 24})
        self.assertEqual(result["date_a_live_filename_hints_by_cohort"],
                         {"new_since_original_58": 24})
        self.assertEqual(result["api_scope"]["full_library_file_lists"], 0)
        self.assertEqual(result["api_scope"]["metadata_refresh_requests"], 0)
        self.assertEqual(result["api_scope"]["xref_writes"], 0)
        self.assertEqual(len(api.calls), 1)
        self.assertTrue(all(f["path"].endswith(".mkv") for f in result["files"]))

    def test_reject_unbounded_or_changing_results_without_partial_success(self):
        for params in [(101, None), (48, 47), (48, 46)]:
            with self.subTest(params=params):
                api = FakeAPI(*params)
                with self.assertRaises(ValueError):
                    snapshot(api)
                self.assertEqual(len(api.calls), 1)
        api = FakeAPI()
        api.files[1]["ID"] = api.files[0]["ID"]
        with self.assertRaises(ValueError):
            snapshot(api)
        with self.assertRaises(ValueError):
            snapshot(api, max_files=101)

    def test_audit_only_nineteen_pinned_ids_and_preserves_uncertainty(self):
        api = FakeAPI()
        report = snapshot(api)
        data = json.loads(NEXT19.read_text(encoding="utf-8"))
        audit = audit_prior_next19(
            api, {x["file_id"] for x in report["files"]}, data)
        self.assertEqual(audit["checked"], 19)
        self.assertEqual(len(api.calls), 20)
        self.assertEqual(len([x for x in api.calls if x[1].startswith("/File/")]), 19)
        self.assertEqual(len(audit["records"]), 19)
        self.assertTrue(all(r["status"] == "record_returned" for r in audit["records"]))
        self.assertTrue(all("cross_reference_fields" in r for r in audit["records"]))
        self.assertIn("not proof", audit["scope"])

    def test_single_file_api_error_does_not_erase_snapshot(self):
        api = FakeAPI()
        data = json.loads(NEXT19.read_text(encoding="utf-8"))
        api.fail_file = data["entries"][0]["file_id"]
        audit = audit_prior_next19(api, set(), data)
        self.assertEqual(audit["checked"], 19)
        self.assertEqual(audit["records"][0]["status"], "api_error")
        self.assertEqual(len(api.calls), 19)

    def test_private_output_and_torrent_path_guard(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "snapshot.json"
            write_private(p, {"x": "value"})
            self.assertEqual(p.stat().st_mode & 0o777, 0o600)
            self.assertEqual(json.loads(p.read_text()), {"x": "value"})
        with self.assertRaises(ValueError):
            write_private("/Anime/report.json", {})


if __name__ == "__main__":
    unittest.main()
