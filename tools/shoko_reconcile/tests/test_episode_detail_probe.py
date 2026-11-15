"""No media walk, Shoko refresh, or full-file scan in manual detail probe."""
import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from episode_detail_probe import inspect, parse_ids, shorten


class FakeAPI:
    def __init__(self):
        self.calls = []

    def local_series(self, aid):
        self.calls.append(("local_series", aid))
        if aid == 14570:
            return None
        return {"IDs": {"ID": aid+100, "AniDB": aid}}

    def pages(self, path, params, size):
        self.calls.append(("pages", path))
        assert path.startswith("/Series/") and path.endswith("/Episode")
        assert params["includeDataFrom"] == "AniDB"
        yield {"ID": 33, "AniDB": {
            "ID": 111, "EpisodeNumber": 1, "Type": "other",
            "Title": "TV version segment 1", "Description": "x" * 700,
            "Titles": [{"Name": "Part 1"}]}}
        yield {"ID": 34, "AniDB": {
            "ID": 112, "EpisodeNumber": 2, "Type": "other",
            "Title": {"English": "Part 2", "Japanese": "日本語"}}}

    def unrecognized(self):
        raise AssertionError("No /File unrecognized enumeration allowed")

    def link(self, *args):
        raise AssertionError("No link writes allowed")

    def refresh_series(self, *args):
        raise AssertionError("No metadata refresh allowed")


class ProbeTests(unittest.TestCase):
    def test_dedup_ids_and_reject_invalid(self):
        self.assertEqual(parse_ids("10691, 17477,10691"), [10691, 17477])
        for invalid in ("abc", "-5", "5;6", "0", "١٠", "nan"):
            with self.subTest(invalid=invalid):
                with self.assertRaises(ValueError):
                    parse_ids(invalid)

    def test_exact_ids_only_and_missed_work_no_episode_fetch(self):
        api = FakeAPI()
        data = inspect(api, [17477, 14570, 17477])
        self.assertEqual(data["ids"], [17477, 14570])
        self.assertEqual(len([c for c in api.calls if c[0] == "local_series"]), 2)
        self.assertEqual(len([c for c in api.calls if c[0] == "pages"]), 1)
        self.assertEqual(data["works"][1]["status"], "missing")
        self.assertEqual(data["works"][0]["episodes"][0]["anidb"]["Type"], "other")
        self.assertEqual(data["works"][0]["episodes"][0]["anidb"]["Title"],
                         "TV version segment 1")
        self.assertEqual(len(data["works"][0]["episodes"][0]["anidb"]["Description"]), 350)
        self.assertEqual(data["api_scope"]["full_file_scans"], 0)
        self.assertEqual(data["api_scope"]["metadata_refresh_or_link_calls"], 0)

    def test_strict_max_ids_prevents_calls(self):
        api = FakeAPI()
        with self.assertRaises(ValueError):
            inspect(api, list(range(1, 12)))
        with self.assertRaises(ValueError):
            inspect(api, [])
        with self.assertRaises(ValueError):
            inspect(api, [0])
        self.assertEqual(api.calls, [])

    def test_nested_fields_sanitized(self):
        self.assertEqual(shorten({"x": ["a", "b", "c"]}, depth=2),
                         {"x": ["a", "b", "c"]})


if __name__ == "__main__":
    unittest.main()
