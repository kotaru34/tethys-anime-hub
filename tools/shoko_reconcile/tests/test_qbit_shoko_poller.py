"""Regression tests for external qBittorrent Anime observer."""
import sys
from pathlib import Path
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import qbit_shoko_poller as poller


HASH_A = "a" * 40
HASH_B = "b" * 40
HASH_C = "c" * 40


def torrent(h, *, tags="Anime", progress=0.5, amount=100,
            completed_on=-1):
    return {"hash": h, "tags": tags, "progress": progress,
            "amount_left": amount, "completion_on": completed_on}


def done(h, tags="Anime", finished=1000):
    return torrent(h, tags=tags, progress=1.0, amount=0, completed_on=finished)


class AnimePollerTest(unittest.TestCase):
    def test_exact_anime_tag_only(self):
        for tags in ["Anime", "Anime, Movies", "Movies,Anime"]:
            self.assertTrue(poller.anime_tag({"tags": tags}))
        for tags in ["anime", "AnimeArt", "Movies", "", None]:
            self.assertFalse(poller.anime_tag({"tags": tags}))

    def test_bootstrap_and_one_completion(self):
        state = poller.new_state()
        config = {"debounce_seconds": 300}
        scans = []
        callback = lambda cfg: scans.append(True)
        self.assertEqual(poller.observe(state, [done(HASH_A), torrent(HASH_B)], 1000), [])
        self.assertIsNone(state["pending_at"])
        self.assertEqual(poller.observe(state, [done(HASH_A), done(HASH_B, finished=1020)], 1025), [HASH_B])
        self.assertFalse(poller.maybe_scan(config, state, 1324, callback))
        self.assertTrue(poller.maybe_scan(config, state, 1325, callback))
        self.assertEqual(len(scans), 1)
        poller.observe(state, [done(HASH_A), done(HASH_B, finished=1020)], 1350)
        self.assertFalse(poller.maybe_scan(config, state, 2000, callback))
        self.assertEqual(len(scans), 1)

    def test_unrelated_torrent_does_not_reset_debounce(self):
        s = poller.new_state()
        poller.observe(s, [torrent(HASH_A)], 900)
        poller.observe(s, [done(HASH_A)], 1000)
        self.assertEqual(s["pending_at"], 1000)
        poller.observe(s, [done(HASH_A), done(HASH_B, "Movies", 1005)], 1060)
        self.assertEqual(s["pending_at"], 1000)
        poller.observe(s, [done(HASH_A), done(HASH_C, finished=1100)], 1110)
        self.assertEqual(s["pending_at"], 1110)
        self.assertEqual(len(s["pending_hashes"]), 2)

    def test_retries_do_not_drop_pending(self):
        s = poller.new_state()
        poller.observe(s, [torrent(HASH_A)], 900)
        poller.observe(s, [done(HASH_A)], 1000)
        count = []
        def fail(cfg):
            count.append("fail")
            raise ConnectionError("Shoko offline")
        self.assertFalse(poller.maybe_scan({}, s, 1301, fail))
        self.assertEqual(s["pending_at"], 1000)
        self.assertEqual(len(count), 1)
        self.assertFalse(poller.maybe_scan({}, s, 1330, fail))
        self.assertEqual(len(count), 1)
        self.assertTrue(poller.maybe_scan({}, s, 1361, lambda _: count.append("success")))
        self.assertEqual(count, ["fail", "success"])
        self.assertIsNone(s["pending_at"])

    def test_state_persists_and_restarts_catch_completion(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "state.json"
            s = poller.new_state()
            poller.observe(s, [torrent(HASH_A)], 100)
            poller.atomic_json(path, s)
            s2 = poller.read_state(path)
            self.assertEqual(poller.observe(s2, [done(HASH_A, finished=120)], 135), [HASH_A])
            poller.atomic_json(path, s2)
            self.assertEqual(poller.read_state(path)["pending_at"], 135)

    def test_invalid_api_snapshot_does_not_mutate_state(self):
        s = poller.new_state()
        with self.assertRaises(ValueError):
            poller.observe(s, {"error": True}, 100)
        self.assertFalse(s["initialized"])

    def test_recompleted_torrent_triggers_once(self):
        s = poller.new_state()
        poller.observe(s, [done(HASH_A, finished=1000)], 1200)
        self.assertEqual(poller.observe(s, [done(HASH_A, finished=2000)], 2001), [HASH_A])
        self.assertEqual(poller.observe(s, [done(HASH_A, finished=2000)], 2002), [])


if __name__ == "__main__":
    unittest.main()
