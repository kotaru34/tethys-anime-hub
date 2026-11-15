"""New 19-file second manual batch, verified AniDB metadata, and no extra scans."""
import json
import os
import sys
import tempfile
import unittest
from collections import Counter
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from manual_review_batch import preflight, apply_batch, validate_manifest, main
from test_manual_review_batch import FakeShoko

SECOND_MANIFEST = Path(__file__).resolve().parents[1] / "manual_xrefs_next19_20261115.json"
PREVIOUS_MANIFEST = Path(__file__).resolve().parents[1] / "manual_xrefs_20261115.json"
EXPECTED_AIDS = {11143: 2, 14397: 1, 14570: 12, 17640: 1, 17862: 1, 18865: 2}
EXPECTED_IDS = {
    3337, 3333, 3344, 3342, 3339, 3340, 3334, 3338, 3341,
    3335, 3336, 3343, 2972, 2973, 2489, 2485, 3037, 3040, 3038,
}


def manifest():
    return json.loads(SECOND_MANIFEST.read_text(encoding="utf-8"))


class SecondManualBatchTests(unittest.TestCase):
    def test_only_nineteen_exact_ids_and_six_works(self):
        data = manifest()
        entries = validate_manifest(data)
        self.assertEqual(len(entries), 19)
        self.assertEqual({x["file_id"] for x in entries}, EXPECTED_IDS)
        self.assertEqual(dict(Counter(e["anidb_id"] for e in entries)),
                         EXPECTED_AIDS)
        self.assertEqual({e["type"] for e in entries}, {"Episode"})
        self.assertEqual(len({(e["anidb_id"], e["type"], e["episode"])
                              for e in entries}), 19)
        self.assertTrue(all(e["anidb_episode_id"] > 0 for e in entries))

    def test_nothing_overlaps_prior_fifteen_or_combined_yona(self):
        first = json.loads(PREVIOUS_MANIFEST.read_text(encoding="utf-8"))
        second = manifest()
        self.assertFalse({e["file_id"] for e in first["entries"]} &
                         {e["file_id"] for e in second["entries"]})
        self.assertNotIn(2486, {e["file_id"] for e in second["entries"]})
        self.assertEqual(
            {(e["file_id"], e["episode"]) for e in second["entries"]
             if e["anidb_id"] == 11143},
            {(2489, 1), (2485, 2)},
        )

    def test_all_nineteen_readonly_preflight_one_file_list_six_local_work_reads(self):
        api = FakeShoko(manifest())
        report = preflight(api, manifest())
        self.assertEqual(report["mode"], "dry_run")
        self.assertEqual(report["counts"], {"ready": 19})
        self.assertEqual(report["api_scope"]["unrecognized_file_enumerations"], 1)
        self.assertEqual(report["api_scope"]["distinct_anidb_work_reads"], 6)
        self.assertEqual(report["api_scope"]["distinct_episode_inventory_reads"], 6)
        self.assertEqual(api.linked, [])
        self.assertFalse(any(x[0] == "link" for x in api.calls))

    def test_all_nineteen_written_only_after_complete_preflight(self):
        api = FakeShoko(manifest())
        report = apply_batch(api, manifest())
        self.assertEqual(report["counts"], {"submitted": 19})
        self.assertEqual(report["submitted"], 19)
        self.assertEqual(len(api.linked), 19)
        self.assertTrue(all(x[3] == "Episode" for x in api.linked))

    def test_changed_one_episode_title_aborts_entire_19_batch(self):
        data = manifest()
        api = FakeShoko(data)
        api.bad_titles = {3343}
        report = apply_batch(api, data)
        self.assertEqual(report["mode"], "apply_aborted_preflight")
        self.assertEqual(report["submitted"], 0)
        self.assertEqual(report["counts"]["blocked"], 1)
        self.assertEqual(api.linked, [])

    def test_changed_path_or_work_aborts_entire_19_batch(self):
        data = manifest()
        api = FakeShoko(data)
        api.bad_paths = {3037}
        report = apply_batch(api, data)
        self.assertEqual(report["submitted"], 0)
        self.assertEqual(api.linked, [])
        api = FakeShoko(data)
        api.bad_series = {18865}
        report = apply_batch(api, data)
        self.assertEqual(report["submitted"], 0)
        self.assertEqual(api.linked, [])

    def test_already_recognized_never_double_links(self):
        api = FakeShoko(manifest())
        api.missing = {3337, 3037}
        report = apply_batch(api, manifest())
        self.assertEqual(report["counts"]["submitted"], 17)
        self.assertEqual(report["counts"]["not_unrecognized_skip"], 2)
        self.assertFalse({3337, 3037} & {x[0] for x in api.linked})

    def test_confirmation_explicitly_matches_batch_size(self):
        data = manifest()
        api = FakeShoko(data)
        with tempfile.TemporaryDirectory() as td:
            output = Path(td) / "result.json"
            with patch("manual_review_batch.ShokoAPI", return_value=api), patch.dict(
                os.environ, {"SHOKO_API_KEY": "fake"}
            ):
                with self.assertRaises(SystemExit) as exc:
                    main(["--manifest", str(SECOND_MANIFEST), "--apply",
                          "--confirm", "APPLY_SHOKO_XREFS_15",
                          "--report", str(output)])
                self.assertEqual(exc.exception.code, 2)
                self.assertEqual(api.linked, [])
                result = main(["--manifest", str(SECOND_MANIFEST), "--apply",
                               "--confirm", "APPLY_SHOKO_XREFS_19",
                               "--report", str(output)])
                self.assertEqual(result, 0)
                self.assertEqual(len(api.linked), 19)
                stored = json.loads(output.read_text(encoding="utf-8"))
                self.assertEqual(stored["counts"], {"submitted": 19})


if __name__ == "__main__":
    unittest.main()
