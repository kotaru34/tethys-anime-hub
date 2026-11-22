"""Two exact Nekopara OVA/ONA XRefs; deliberately never link Yona here."""
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from manual_review_batch import validate_manifest, preflight, apply_batch
from test_manual_review_batch import FakeShoko

MANIFEST = Path(__file__).resolve().parents[1] / "manual_xrefs_nekopara_ova_ona_20261122.json"


def manifest():
    return json.loads(MANIFEST.read_text(encoding="utf-8"))


class NekoparaStandaloneXRefsTests(unittest.TestCase):
    def test_exact_two_not_tv_or_trailer_or_yona(self):
        entries = validate_manifest(manifest())
        self.assertEqual(len(entries), 2)
        self.assertEqual({e["file_id"] for e in entries}, {2909, 2850})
        self.assertEqual({e["anidb_id"] for e in entries}, {12622, 14206})
        self.assertEqual({e["shoko_series_id"] for e in entries}, {274, 279})
        self.assertEqual({e["anidb_episode_id"] for e in entries}, {193701, 203599})
        self.assertEqual({(e["type"], e["episode"]) for e in entries}, {("Episode", 1)})
        self.assertTrue(all(not e["path"].startswith("/") for e in entries))

    def test_read_only_preflight_one_unrecognized_enumeration_two_works(self):
        api = FakeShoko(manifest())
        result = preflight(api, manifest())
        self.assertEqual(result["mode"], "dry_run")
        self.assertEqual(result["counts"], {"ready": 2})
        self.assertEqual(result["api_scope"]["unrecognized_file_enumerations"], 1)
        self.assertEqual(result["api_scope"]["distinct_anidb_work_reads"], 2)
        self.assertEqual(result["api_scope"]["distinct_episode_inventory_reads"], 2)
        self.assertEqual(api.linked, [])
        self.assertFalse(any(x[0] == "link" for x in api.calls))

    def test_two_correct_links_only_after_preflight(self):
        api = FakeShoko(manifest())
        result = apply_batch(api, manifest())
        self.assertEqual(result["mode"], "apply")
        self.assertEqual(result["counts"], {"submitted": 2})
        self.assertEqual(set(api.linked), {
            (2909, 274, 1, "Episode"), (2850, 279, 1, "Episode")})

    def test_changed_path_or_work_or_episode_is_all_or_nothing(self):
        entries = manifest()
        for attr, value in [
            ("bad_paths", 2909),
            ("bad_series", 14206),
            ("bad_titles", 2850),
        ]:
            api = FakeShoko(entries)
            getattr(api, attr).add(value)
            report = apply_batch(api, entries)
            self.assertEqual(report["mode"], "apply_aborted_preflight")
            self.assertEqual(report["submitted"], 0)
            self.assertEqual(api.linked, [])

    def test_automatically_recognized_file_is_skipped(self):
        api = FakeShoko(manifest())
        api.missing.add(2909)
        report = apply_batch(api, manifest())
        self.assertEqual(report["submitted"], 1)
        self.assertEqual(report["counts"], {
            "not_unrecognized_skip": 1, "submitted": 1})
        self.assertEqual(api.linked, [(2850, 279, 1, "Episode")])

    def test_both_already_recognized_never_write(self):
        api = FakeShoko(manifest())
        api.missing = {2909, 2850}
        report = apply_batch(api, manifest())
        self.assertEqual(report["counts"], {"not_unrecognized_skip": 2})
        self.assertEqual(report["submitted"], 0)
        self.assertEqual(api.linked, [])


if __name__ == "__main__":
    unittest.main()
