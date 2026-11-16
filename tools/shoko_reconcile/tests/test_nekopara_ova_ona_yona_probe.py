"""Tests: two-work metadata bootstrap and read-only combined Yona OVA probe."""
import json
from pathlib import Path
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from nekopara_ova_ona_bootstrap import ALLOWED_AIDS, WORKS, apply, load_state, preflight
from yona_03_sp_probe import (
    AID, FILE_ID, RELATIVE_PATH, SHOKO_SID, TARGETS, probe_media,
    shoko_identity, inspect,
)


class FakeNekopara:
    def __init__(self):
        self.calls = []
        self.local = {}
        self.get_error = None
        self.post_error = None

    def local_series(self, aid):
        self.calls.append(("GET", aid))
        if aid == self.get_error:
            raise RuntimeError("GET failed")
        if aid not in self.local:
            return None
        return {"IDs": {"ID": self.local[aid], "AniDB": aid}}

    def refresh_series(self, aid):
        self.calls.append(("POST", aid))
        if aid == self.post_error:
            raise TimeoutError("uncertain write response")

    def pages(self, path, params, size):
        self.calls.append(("PAGES", path))
        assert path.startswith("/Series/") and path.endswith("/Episode")
        return [{"AniDB": {"ID": 1010, "Type": "Episode",
                           "EpisodeNumber": 1, "Title": "OVA"}}]

    def unrecognized(self):
        raise AssertionError("No /File listings allowed")

    def link(self, *args, **kwargs):
        raise AssertionError("No XRef writes allowed")


class FakeYona:
    def __init__(self):
        self.calls = []
        self.bad_path = False
        self.bad_target = False
        self.bad_sid = False

    def request(self, method, path, params=None):
        self.calls.append((method, path))
        if (method, path) != ("GET", f"/File/{FILE_ID}"):
            raise AssertionError("Wrong Shoko endpoint")
        return {"ID": FILE_ID, "Locations": [{"RelativePath":
                "wrong/file.mkv" if self.bad_path else RELATIVE_PATH}]}

    def local_series(self, aid):
        self.calls.append(("local_series", aid))
        if aid != AID:
            raise AssertionError("Wrong AniDB work")
        return {"IDs": {"ID": SHOKO_SID + int(self.bad_sid), "AniDB": AID}}

    def pages(self, path, params, size):
        self.calls.append(("pages", path))
        if path != f"/Series/{SHOKO_SID}/Episode":
            raise AssertionError("Wrong work episodes")
        return [{"AniDB": {"ID": ep["anidb_episode_id"],
                           "Type": ep["type"], "EpisodeNumber": ep["number"],
                           "Title": ep["title"] + (".changed" if self.bad_target else "")}}
                for ep in TARGETS]

    def unrecognized(self):
        raise AssertionError("No /File enumeration")

    def link(self, *args):
        raise AssertionError("No XRef writes")

    def refresh_series(self, *args):
        raise AssertionError("No metadata writes")


class NekoparaTwoWorkTests(unittest.TestCase):
    def test_exact_only_two_reviews(self):
        self.assertEqual(ALLOWED_AIDS, {12622, 14206})
        self.assertEqual({w["file_id"] for w in WORKS}, {2909, 2850})
        self.assertTrue(all(w["path"].endswith(".mkv") for w in WORKS))

    def test_dry_run_two_local_reads_no_file_enumeration(self):
        api = FakeNekopara()
        report = preflight(api, {"schema": 1, "attempts": {}})
        self.assertEqual(report["counts"], {"missing": 2})
        self.assertEqual(report["scope"]["targeted_work_gets"], 2)
        self.assertEqual(report["scope"]["unrecognized_file_scans"], 0)
        self.assertEqual(report["scope"]["xref_writes"], 0)
        self.assertEqual(api.calls, [("GET", 12622), ("GET", 14206)])

    def test_two_writes_persisted_before_dispatch_no_repeats(self):
        api = FakeNekopara()
        state = {"schema": 1, "attempts": {}}
        saved, paused = [], []
        report = apply(api, state, lambda obj: saved.append(json.loads(json.dumps(obj))),
                       sleep=lambda secs: paused.append(secs), now=lambda: 1234)
        self.assertEqual(report["submitted"], 2)
        self.assertEqual(len(saved), 4)
        self.assertEqual(saved[0]["attempts"]["12622"]["outcome"], "dispatch_uncertain")
        self.assertEqual(saved[1]["attempts"]["12622"]["outcome"], "requested")
        self.assertEqual(paused, [2])
        api.calls.clear()
        report = apply(api, state, lambda _: self.fail("no repeat write"))
        self.assertEqual(report["submitted"], 0)
        self.assertEqual(report["counts"], {"previously_requested_pending": 2})
        self.assertEqual(api.calls, [("GET", 12622), ("GET", 14206)])

    def test_existing_work_skipped(self):
        api = FakeNekopara()
        api.local[12622] = 201
        report = apply(api, {"schema": 1, "attempts": {}},
                       lambda _: None)
        self.assertEqual(report["submitted"], 1)
        self.assertEqual(report["counts"], {"present": 1, "requested": 1})
        self.assertEqual([x for x in api.calls if x[0] == "POST"],
                         [("POST", 14206)])

    def test_failed_preflight_aborts_all_writes(self):
        api = FakeNekopara()
        api.get_error = 14206
        report = apply(api, {"schema": 1, "attempts": {}},
                       lambda _: self.fail("No state update on failed preflight"))
        self.assertEqual(report["mode"], "apply_aborted_preflight")
        self.assertEqual(report["submitted"], 0)
        self.assertFalse(any(c[0] == "POST" for c in api.calls))

    def test_uncertain_request_persisted_and_no_retry(self):
        api = FakeNekopara()
        api.post_error = 12622
        state = {"schema": 1, "attempts": {}}
        report = apply(api, state, lambda _: None)
        self.assertEqual(report["attempted"], 1)
        self.assertEqual(report["submitted"], 0)
        self.assertEqual(state["attempts"]["12622"]["outcome"],
                         "request_error_uncertain")
        self.assertEqual(len([c for c in api.calls if c[0] == "POST"]), 1)
        api.post_error = None
        report = apply(api, state, lambda _: None)
        self.assertEqual(report["submitted"], 1)
        self.assertEqual(len([c for c in api.calls if c == ("POST", 12622)]), 1)

    def test_episode_check_after_metadata_loaded(self):
        api = FakeNekopara()
        api.local = {12622: 201, 14206: 202}
        report = preflight(api, {"schema": 1, "attempts": {}}, check=True)
        self.assertEqual(report["counts"], {"present_ready": 2})
        self.assertEqual(report["scope"]["episode_inventory_gets"], 2)
        self.assertTrue(all(w["episodes"][0]["anidb_episode_id"] == 1010
                            for w in report["works"]))
        self.assertEqual(len(api.calls), 4)

    def test_reject_unapproved_state_attempts(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "state.json"
            p.write_text(json.dumps({"schema": 1, "attempts": {"14570": {}}}))
            with self.assertRaises(ValueError):
                load_state(p)


class YonaProbeTests(unittest.TestCase):
    def test_exact_shoko_identity_only_three_reads(self):
        api = FakeYona()
        row = shoko_identity(api)
        self.assertTrue(row["file_path_verified"])
        self.assertEqual(len(row["verified_episode_candidates"]), 2)
        self.assertEqual(row["verified_episode_candidates"][0]["anidb_episode_id"], 176847)
        self.assertEqual(row["verified_episode_candidates"][1]["anidb_episode_id"], 183623)
        self.assertEqual(len(api.calls), 3)

    def test_fail_closed_on_wrong_file_or_episode_or_series(self):
        for flag in ("bad_path", "bad_target", "bad_sid"):
            with self.subTest(flag=flag):
                api = FakeYona()
                setattr(api, flag, True)
                with self.assertRaises(ValueError):
                    shoko_identity(api)

    def test_missing_media_is_explicitly_reported_not_claimed_verified(self):
        with tempfile.TemporaryDirectory() as td:
            result = probe_media(Path(td))
            self.assertEqual(result["status"], "media_path_unavailable")

    def test_ffprobe_headers_and_chapters_no_content_claim(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            movie = root / RELATIVE_PATH
            movie.parent.mkdir()
            movie.write_bytes(b"\x1a\x45\xdf\xa3")
            calls = []
            def fake_run(command, **kwargs):
                calls.append(command)
                return SimpleNamespace(returncode=0, stderr="", stdout=json.dumps({
                    "format": {"duration": "1670.5", "size": "1000000"},
                    "chapters": [
                        {"start_time": "0.000000", "end_time": "1400.000000",
                         "tags": {"title": "OVA E03"}},
                        {"start_time": "1400.000000", "end_time": "1670.500000",
                         "tags": {"title": "SP"}}],
                    "streams": [{"codec_type": "video", "codec_name": "hevc"}],
                }))
            result = probe_media(root, ffprobe="/usr/bin/ffprobe", run=fake_run)
            self.assertEqual(result["status"], "probed")
            self.assertEqual(result["duration_minutes"], 27.84)
            self.assertEqual(len(result["chapters"]), 2)
            self.assertEqual(len(calls), 1)
            self.assertIn("cannot prove", result["interpretation"])
            self.assertEqual([x for x in movie.parent.iterdir()], [movie])

    def test_combined_inspection_zero_writes(self):
        api = FakeYona()
        with tempfile.TemporaryDirectory() as td:
            report = inspect(api, Path(td))
        self.assertEqual(report["scope"]["xref_writes"], 0)
        self.assertEqual(report["media"]["status"], "media_path_unavailable")
        self.assertEqual(len(report["potential_links_if_content_verified"]), 2)


if __name__ == "__main__":
    unittest.main()
