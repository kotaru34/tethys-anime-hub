"""One-shot 6-work metadata queue: no duplicate work, no XRefs, no filesystem scan."""
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from targeted_metadata_bootstrap import (
    MANIFEST, atomic_json, episode_details, exclusive_state_lock,
    load_state, preflight, request_missing, validate,
)


def sample_manifest():
    return json.loads(MANIFEST.read_text(encoding="utf-8"))


def empty_state():
    return {"schema": 1, "attempts": {}}


class FakeShoko:
    def __init__(self):
        self.calls = []
        self.present = {}
        self.fails = set()
        self.error_get = set()
        self.bad_work = set()
        self.work_episodes = {}

    def local_series(self, aid):
        self.calls.append(("local_series", aid))
        if aid in self.error_get:
            raise RuntimeError("Temporary GET failure")
        if aid not in self.present:
            return None
        return {"IDs": {"ID": self.present[aid],
                        "AniDB": aid + (1 if aid in self.bad_work else 0)}}

    def refresh_series(self, aid):
        self.calls.append(("refresh_series", aid))
        if aid in self.fails:
            raise RuntimeError("Ambiguous response after timeout")
        # Asynchronous metadata: accepting the refresh does not immediately
        # make the work local; no automatic retries are allowed.

    def pages(self, path, params, size=500):
        self.calls.append(("pages", path))
        assert path.startswith("/Series/") and path.endswith("/Episode")
        assert params["includeDataFrom"] == "AniDB"
        sid = int(path.split("/")[2])
        return [{"AniDB": {"ID": sid * 1000 + n, "Type": "Episode",
                           "EpisodeNumber": n, "Title": f"Episode {n}"}}
                for n in self.work_episodes.get(sid, range(1, 13))]

    def unrecognized(self):
        raise AssertionError("No /File scans allowed")

    def link(self, *args):
        raise AssertionError("No episode XRef writes allowed")

    def anime_search(self, *args):
        raise AssertionError("No fuzzy Shoko title searches allowed")


class TargetedMetadataTests(unittest.TestCase):
    def test_exactly_six_works_and_twenty_file_ids(self):
        data = sample_manifest()
        works = validate(data)
        self.assertEqual(len(works), 6)
        self.assertEqual(sum(len(w["expected_file_ids"]) for w in works), 20)
        self.assertEqual(len({fid for w in works for fid in w["expected_file_ids"]}), 20)

    def test_default_dry_run_is_only_six_local_gets(self):
        api = FakeShoko()
        report = preflight(api, sample_manifest(), empty_state())
        self.assertEqual(report["counts"], {"missing": 6})
        self.assertEqual(report["scope"]["local_work_gets"], 6)
        self.assertEqual(report["scope"]["episode_inventory_reads"], 0)
        self.assertEqual(report["scope"]["media_walks"], 0)
        self.assertEqual(report["scope"]["full_file_scans"], 0)
        self.assertEqual(report["scope"]["xref_writes"], 0)
        self.assertEqual(len(api.calls), 6)
        self.assertTrue(all(call[0] == "local_series" for call in api.calls))

    def test_apply_six_post_at_most_once_and_paced(self):
        api = FakeShoko()
        state, saved, sleeps = empty_state(), [], []
        report = request_missing(
            api, sample_manifest(), state,
            lambda s: saved.append(json.loads(json.dumps(s))),
            sleep=lambda seconds: sleeps.append(seconds), pause_seconds=2,
            now=lambda: 1000)
        self.assertEqual(report["mode"], "apply")
        self.assertEqual(report["requests_submitted"], 6)
        self.assertEqual(len(sleeps), 5)
        self.assertEqual(sleeps, [2] * 5)
        self.assertEqual(len(saved), 12)  # persisted before AND after POST
        self.assertEqual(len(state["attempts"]), 6)
        self.assertEqual({a["outcome"] for a in state["attempts"].values()},
                         {"requested"})
        self.assertEqual(len([x for x in api.calls if x[0] == "refresh_series"]), 6)

        api.calls.clear()
        report = request_missing(api, sample_manifest(), state,
                                 lambda s: self.fail("state should not change"),
                                 sleep=lambda _: self.fail("no further requests"))
        self.assertEqual(report["requests_submitted"], 0)
        self.assertEqual(report["counts"], {"previously_requested_pending": 6})
        self.assertEqual(len(api.calls), 6)
        self.assertFalse(any(c[0] == "refresh_series" for c in api.calls))

    def test_skip_already_existing_works(self):
        api = FakeShoko()
        api.present = {14570: 42, 11143: 45}
        state = empty_state()
        report = request_missing(api, sample_manifest(), state, lambda s: None,
                                 pause_seconds=0, sleep=lambda _: None)
        self.assertEqual(report["requests_submitted"], 4)
        self.assertEqual(report["counts"], {"present": 2, "requested": 4})
        self.assertEqual(set(state["attempts"]), {
            "18865", "14397", "17640", "17862"})
        self.assertEqual(len([c for c in api.calls if c[0] == "refresh_series"]), 4)

    def test_one_failed_get_aborts_every_post(self):
        api = FakeShoko()
        api.error_get = {18865}
        report = request_missing(api, sample_manifest(), empty_state(),
                                 lambda s: self.fail("no state writes"))
        self.assertEqual(report["mode"], "apply_aborted_failed_preflight")
        self.assertEqual(report["requests_submitted"], 0)
        self.assertEqual(report["counts"]["api_error"], 1)
        self.assertFalse(any(c[0] == "refresh_series" for c in api.calls))

    def test_wrong_existing_work_identity_aborts_every_post(self):
        api = FakeShoko()
        api.present = {14570: 33}
        api.bad_work = {14570}
        report = request_missing(api, sample_manifest(), empty_state(),
                                 lambda s: self.fail("no state writes"))
        self.assertEqual(report["counts"]["blocked_identity_mismatch"], 1)
        self.assertEqual(report["requests_submitted"], 0)

    def test_uncertain_post_error_stops_and_does_not_retry(self):
        api = FakeShoko()
        api.fails = {18865}
        state = empty_state()
        saved = []
        report = request_missing(api, sample_manifest(), state,
                                 lambda s: saved.append(json.loads(json.dumps(s))),
                                 pause_seconds=0, sleep=lambda _: None)
        self.assertEqual(report["requests_submitted"], 1)
        self.assertEqual(report["request_errors"], 1)
        self.assertEqual(report["counts"]["request_error_uncertain"], 1)
        self.assertEqual(len([c for c in api.calls if c[0] == "refresh_series"]), 2)
        self.assertEqual(state["attempts"]["18865"]["outcome"],
                         "request_error_uncertain")
        retry = request_missing(api, sample_manifest(), state,
                                lambda s: self.fail("no second POST"), pause_seconds=0,
                                sleep=lambda _: None)
        self.assertEqual(retry["requests_submitted"], 4)
        self.assertEqual(len([c for c in api.calls
                              if c == ("refresh_series", 18865)]), 1)

    def test_state_is_persisted_before_network_dispatch(self):
        api = FakeShoko()
        state = empty_state()
        observed = []
        def record(s):
            observed.append({k: dict(v) for k, v in s["attempts"].items()})
        request_missing(api, sample_manifest(), state, record,
                        pause_seconds=0, sleep=lambda _: None)
        self.assertEqual(observed[0]["14570"]["outcome"], "dispatch_uncertain")
        self.assertEqual(observed[1]["14570"]["outcome"], "requested")

    def test_later_check_reads_only_six_episode_inventories(self):
        api = FakeShoko()
        api.present = {w["anidb_id"]: i + 100
                       for i, w in enumerate(sample_manifest()["works"])}
        report = preflight(api, sample_manifest(), empty_state(),
                           include_episodes=True)
        self.assertEqual(report["counts"], {"present_ready": 6})
        self.assertEqual(report["scope"]["episode_inventory_reads"], 6)
        self.assertEqual(len([c for c in api.calls if c[0] == "pages"]), 6)
        self.assertEqual(report["works"][0]["ordinary_episode_numbers"],
                         list(range(1, 13)))
        self.assertEqual(report["works"][0]["episodes"][0]["anidb_episode_id"],
                         100001)

    def test_manifest_cannot_expand_to_other_anime(self):
        src = sample_manifest()
        for mutation in ("add", "id", "file", "duplicate"):
            data = json.loads(json.dumps(src))
            if mutation == "add":
                data["works"].append(data["works"][0])
            elif mutation == "id":
                data["works"][0]["anidb_id"] = 123
            elif mutation == "file":
                data["works"][0]["expected_file_ids"][0] = 8888
            else:
                data["works"][0]["expected_file_ids"].append(
                    data["works"][0]["expected_file_ids"][0])
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                validate(data)

    def test_private_state_writes_and_locking(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "state.json"
            atomic_json(path, empty_state())
            self.assertEqual(os.stat(path).st_mode & 0o777, 0o600)
            self.assertEqual(load_state(path), empty_state())
            with exclusive_state_lock(path):
                with self.assertRaises(BlockingIOError):
                    with exclusive_state_lock(path):
                        pass
            with exclusive_state_lock(path):
                pass


if __name__ == "__main__":
    unittest.main()
