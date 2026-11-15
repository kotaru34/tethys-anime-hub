"""Curated manual batch must never mutate Shoko on dry run or failed preflight."""
import json
import sys
import unittest
from copy import deepcopy
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from manual_review_batch import DEFAULT_MANIFEST, apply_batch, preflight, validate_manifest


def manifest():
    return json.loads(DEFAULT_MANIFEST.read_text(encoding="utf-8"))


class FakeShoko:
    def __init__(self, data):
        self.entries = data["entries"]
        self.linked = []
        self.calls = []
        self.bad_paths = set()
        self.bad_titles = set()
        self.bad_series = set()
        self.missing = set()
        self.fail_link = None

    def unrecognized(self):
        self.calls.append(("unrecognized",))
        return [{"ID": e["file_id"],
                 "Locations": [{"RelativePath":
                     e["path"] + (".changed" if e["file_id"] in self.bad_paths else "")}]}
                for e in self.entries if e["file_id"] not in self.missing]

    def local_series(self, aid):
        self.calls.append(("local_series", aid))
        e = next(e for e in self.entries if e["anidb_id"] == aid)
        return {"IDs": {"ID": e["shoko_series_id"]
                        + (1 if aid in self.bad_series else 0),
                        "AniDB": aid}}

    def pages(self, path, params, size):
        self.calls.append(("pages", path))
        assert path.startswith("/Series/") and path.endswith("/Episode")
        assert params["includeDataFrom"] == "AniDB"
        sid = int(path.split("/")[2])
        episodes = {}
        for e in self.entries:
            if e["shoko_series_id"] != sid:
                continue
            ep = (e["type"], e["episode"])
            episodes[ep] = {
                "AniDB": {
                    "ID": e["anidb_episode_id"],
                    "Type": e["type"],
                    "EpisodeNumber": e["episode"],
                    "Title": e["title"] + (".changed" if e["file_id"] in self.bad_titles else "")}}
        return list(episodes.values())

    def link(self, fid, sid, number, kind):
        self.calls.append(("link", fid))
        if fid == self.fail_link:
            raise RuntimeError("Simulated write error")
        self.linked.append((fid, sid, number, kind))

    def refresh_series(self, *args, **kwargs):
        raise AssertionError("No Shoko metadata refresh allowed")


class ManualReviewBatchTests(unittest.TestCase):
    def test_one_file_and_one_episode_identity_per_entry(self):
        data = manifest()
        self.assertEqual(len(validate_manifest(data)), 15)
        self.assertEqual(len({e["file_id"] for e in data["entries"]}), 15)
        self.assertEqual(len({e["anidb_id"] for e in data["entries"]}), 7)
        self.assertEqual(len({(e["anidb_id"], e["type"], e["episode"])
                              for e in data["entries"]}), 15)

    def test_readonly_preflight_has_one_unknown_scan_and_seven_episode_reads(self):
        data = manifest()
        api = FakeShoko(data)
        report = preflight(api, data)
        self.assertEqual(report["counts"], {"ready": 15})
        self.assertEqual(report["mode"], "dry_run")
        self.assertEqual(report["api_scope"]["unrecognized_file_enumerations"], 1)
        self.assertEqual(report["api_scope"]["distinct_anidb_work_reads"], 7)
        self.assertEqual(report["api_scope"]["distinct_episode_inventory_reads"], 7)
        self.assertEqual(len([c for c in api.calls if c[0] == "unrecognized"]), 1)
        self.assertEqual(len([c for c in api.calls if c[0] == "pages"]), 7)
        self.assertEqual(api.linked, [])
        self.assertTrue(any(r["type"] == "Other" for r in report["rows"]))

    def test_all_fifteen_only_written_after_everything_passes(self):
        data = manifest()
        api = FakeShoko(data)
        result = apply_batch(api, data)
        self.assertEqual(result["mode"], "apply")
        self.assertEqual(result["submitted"], 15)
        self.assertEqual(len(api.linked), 15)
        self.assertEqual({kind for _, _, _, kind in api.linked},
                         {"Episode", "Special", "Other"})

    def test_changed_path_aborts_entire_batch_with_zero_writes(self):
        data = manifest()
        api = FakeShoko(data)
        api.bad_paths.add(data["entries"][13]["file_id"])
        report = apply_batch(api, data)
        self.assertEqual(report["mode"], "apply_aborted_preflight")
        self.assertEqual(report["counts"]["blocked"], 1)
        self.assertEqual(report["submitted"], 0)
        self.assertEqual(api.linked, [])

    def test_changed_episode_title_aborts_before_writes(self):
        data = manifest()
        api = FakeShoko(data)
        api.bad_titles.add(data["entries"][0]["file_id"])
        report = apply_batch(api, data)
        self.assertEqual(report["counts"]["blocked"], 1)
        self.assertEqual(report["submitted"], 0)
        self.assertEqual(api.linked, [])

    def test_changed_series_identity_aborts_before_writes(self):
        data = manifest()
        api = FakeShoko(data)
        api.bad_series.add(17477)
        report = apply_batch(api, data)
        self.assertEqual(report["counts"]["blocked"], 3)
        self.assertEqual(report["submitted"], 0)
        self.assertEqual(api.linked, [])

    def test_already_recognized_or_removed_id_is_never_linked_twice(self):
        data = manifest()
        api = FakeShoko(data)
        api.missing.add(3321)
        report = apply_batch(api, data)
        self.assertEqual(report["submitted"], 14)
        self.assertEqual(report["counts"]["not_unrecognized_skip"], 1)
        self.assertNotIn(3321, [x[0] for x in api.linked])
        api.missing = {e["file_id"] for e in data["entries"]}
        report = apply_batch(api, data)
        self.assertEqual(report["submitted"], 0)
        self.assertEqual(report["counts"], {"not_unrecognized_skip": 15})

    def test_failed_link_stops_remaining_writes(self):
        data = manifest()
        api = FakeShoko(data)
        api.fail_link = 3345
        report = apply_batch(api, data)
        self.assertEqual(report["mode"], "apply_partial_error")
        self.assertEqual(report["submitted"], 3)
        self.assertEqual(len(api.linked), 3)
        self.assertEqual(report["counts"]["write_failed"], 1)

    def test_reject_wrong_or_duplicate_targets_before_shoko_calls(self):
        original = manifest()
        for data in (
            {"schema": 0, "entries": original["entries"]},
            {**original, "entries": original["entries"] + [original["entries"][0]]},
            {**original, "entries": [{**original["entries"][0], "path": "/Anime/foo"}]},
            {**original, "entries": [{**original["entries"][0], "file_id": 0}]},
            {**original, "entries": [{**original["entries"][0], "type": "Movie"}]},
        ):
            with self.subTest(data=str(data)[:60]):
                with self.assertRaises(ValueError):
                    validate_manifest(data)


if __name__ == "__main__":
    unittest.main()
