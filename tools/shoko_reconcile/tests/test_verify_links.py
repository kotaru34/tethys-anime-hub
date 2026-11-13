"""Read-only Shoko XRef verifier regression tests; no live API calls."""
import json
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from verify_links import expected_from_plans, verify


class FakeAPI:
    def __init__(self):
        self.references = [(101, 55, "User")]
        self.file_path = "Media/Work - 03.mkv"
        self.episode = 3
        self.calls = []

    def local_series(self, aid):
        self.calls.append(("series", aid))
        return {"IDs": {"ID": 5, "AniDB": 101}}

    def pages(self, route, params):
        self.calls.append(("pages", route))
        yield {"IDs": {"ID": 55}, "AniDB": {
            "Type": "Episode", "EpisodeNumber": self.episode}}

    def request(self, method, route, params):
        self.calls.append((method, route))
        return {"ID": 7,
                "Locations": [{"RelativePath": self.file_path}],
                "SeriesIDs": [{
                    "SeriesID": {"AniDB": aid},
                    "EpisodeIDs": [{"ID": ep, "Source": source}]
                } for aid, ep, source in self.references]}


EXPECTED = {7: (101, "Episode", 3, "Media/Work - 03.mkv")}


class VerifierTests(unittest.TestCase):
    def test_success_has_one_matching_xref(self):
        api = FakeAPI()
        lines = []
        self.assertEqual(verify(api, EXPECTED, printer=lines.append), (1, 1))
        self.assertTrue(lines[0].startswith("PASS"))
        self.assertEqual(len([x for x in api.calls if x[0] == "GET"]), 1)
        self.assertFalse(any(x[0] in ("POST", "PUT", "DELETE", "PATCH") for x in api.calls))

    def test_extra_reference_must_fail(self):
        api = FakeAPI()
        api.references.append((999, 77, "User"))
        lines = []
        self.assertEqual(verify(api, EXPECTED, printer=lines.append), (0, 1))
        self.assertIn("extra references", lines[0])

    def test_wrong_episode_must_fail(self):
        api = FakeAPI()
        api.references = [(101, 99, "User")]
        self.assertEqual(verify(api, EXPECTED, printer=lambda _: None), (0, 1))

    def test_wrong_episode_metadata_must_fail(self):
        api = FakeAPI()
        api.episode = 4
        self.assertEqual(verify(api, EXPECTED, printer=lambda _: None), (0, 1))

    def test_stale_path_must_fail(self):
        api = FakeAPI()
        api.file_path = "Other/Work - 03.mkv"
        self.assertEqual(verify(api, EXPECTED, printer=lambda _: None), (0, 1))

    def test_file_id_dedup_and_conflict(self):
        plan = {"version": 2, "groups": [
            {"files": [{"file_id": 7, "target_anidb_id": 101,
                        "episode_type": "Episode", "episode": 3,
                        "path": "Media/Work - 03.mkv", "mode": "auto_evidence"}]}]}
        with TemporaryDirectory() as directory:
            a = Path(directory) / "a.json"
            b = Path(directory) / "b.json"
            a.write_text(json.dumps(plan))
            b.write_text(json.dumps(plan))
            self.assertEqual(expected_from_plans([a, b]), EXPECTED)
            plan["groups"][0]["files"][0]["episode"] = 4
            b.write_text(json.dumps(plan))
            with self.assertRaisesRegex(ValueError, "Conflicting plans"):
                expected_from_plans([a, b])


if __name__ == "__main__":
    unittest.main()
