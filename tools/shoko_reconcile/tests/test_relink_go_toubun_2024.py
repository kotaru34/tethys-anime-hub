"""Strict preflight before replacing the incorrect 2023 special links."""
import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from relink_go_toubun_2024 import inspect


class API:
    def __init__(self):
        self.files = {
            fid: {
                "ID": fid,
                "Locations": [{"RelativePath": "Go-Toubun no Hanayome~ - AniLibria.TV [WEBRip 1080p HEVC]/"
                               f"Go-Toubun_no_Hanayome~_[{ep:02d}]_[AniLibria_TV]_[WEBRip_1080p_HEVC].mkv"}],
                "SeriesIDs": [{"SeriesID": {"AniDB": 17968},
                               "EpisodeIDs": [{"Source": "Manual"}]}],
            } for fid, ep in [(778, 1), (779, 2)]
        }
        self.actions = []
    def local_series(self, aid): return {"IDs": {"AniDB": 18603, "ID": 22}}
    def available_episodes(self, sid): return {("Episode", 1), ("Episode", 2)}
    def pages(self, path, params, size=100):
        return [
            {"AniDB": {"Type": "Other", "EpisodeNumber": 1, "ID": 290245,
                       "Title": "Operation Quintuplets (Part 1)"}},
            {"AniDB": {"Type": "Other", "EpisodeNumber": 2, "ID": 290246,
                       "Title": "Operation Quintuplets (Part 2)"}},
        ]
    def request(self, method, path, params=None):
        self.actions.append((method, path, params))
        return self.files[int(path.rsplit("/", 1)[1])]


class RelinkTests(unittest.TestCase):
    def test_correct_preflight_is_read_only(self):
        api = API()
        sid, rows = inspect(api)
        self.assertEqual(sid, 22)
        self.assertEqual([r["status"] for r in rows], ["ready", "ready"])
        self.assertTrue(all(m == "GET" for m, _, _ in api.actions))
    def test_other_episodes_require_explicit_target_type(self):
        class AniDBSplitAPI(API):
            def available_episodes(self, sid):
                return {("Episode", 1), ("Other", 1), ("Other", 2)}
        api = AniDBSplitAPI()
        with self.assertRaises(RuntimeError):
            inspect(api)
        sid, rows = inspect(api, target_type="Other")
        self.assertEqual(sid, 22)
        self.assertEqual([r["target_type"] for r in rows], ["Other", "Other"])
        self.assertEqual([r["status"] for r in rows], ["ready", "ready"])

    def test_mismatch_in_other_episode_identity_is_rejected(self):
        class WrongOther(API):
            def pages(self, path, params, size=100):
                rows = super().pages(path, params, size=size)
                rows[1]["AniDB"]["ID"] = 12345
                return rows
        with self.assertRaises(RuntimeError):
            inspect(WrongOther(), target_type="Other")

    def test_mismatched_series_fails_closed(self):
        api = API()
        api.files[778]["SeriesIDs"][0]["SeriesID"]["AniDB"] = 18603
        _, rows = inspect(api)
        self.assertEqual(rows[0]["status"], "already_correct")
        api.files[778]["SeriesIDs"][0]["SeriesID"]["AniDB"] = 14247
        with self.assertRaises(RuntimeError):
            inspect(api)
    def test_new_path_must_not_be_silently_relinked(self):
        api = API()
        api.files[778]["Locations"][0]["RelativePath"] = "another-file.mkv"
        with self.assertRaises(RuntimeError):
            inspect(api)
    def test_native_anidb_identity_must_be_preserved(self):
        api = API()
        api.files[778]["SeriesIDs"][0]["EpisodeIDs"][0]["Source"] = "AniDB"
        with self.assertRaises(RuntimeError):
            inspect(api)


if __name__ == "__main__":
    unittest.main()
