"""Verify target-only Shoko AniDB refresh and cheap metadata readiness monitoring."""
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from event_bridge import Coordinator, retry_delay_for
from verified_tv_batch import promote_verified_tv_batch, tv_batch_proof


FOLDER = "Goblin Slayer 2 - AniLibria.TV [WEBRip 1080p HEVC]"


def sample_plan():
    group = {"folder": FOLDER, "candidates": [
        {"anidb_id": 16027, "title": "Goblin Slayer II", "type": "TV",
         "score": 1.0, "season": 2},
        {"anidb_id": 13831, "title": "Goblin Slayer", "type": "TV",
         "score": 0.871, "season": None}],
        "files": [
            {"file_id": 100 + n,
             "path": f"{FOLDER}/Goblin_Slayer_2_[{n:02}]_[HEVC].mkv",
             "episode": n, "source_episode": None,
             "episode_type": "Episode", "target_anidb_id": 16027,
             "mode": "strong_context"}
            for n in range(1, 13)]}
    return {"version": 2, "groups": [group]}


class API:
    def __init__(self, state="missing", episodes=None):
        self.state = state
        self.episodes = episodes
        self.refreshes = []
        self.lookups = 0

    def local_series(self, aid):
        self.lookups += 1
        if self.state == "missing":
            return None
        return {"IDs": {"ID": 55, "AniDB": aid}}

    def available_episodes(self, series_id):
        self.lookups += 1
        if self.state == "empty":
            return set()
        return self.episodes or {
            ("Episode", n) for n in range(1, 13)}

    def refresh_series(self, aid):
        self.refreshes.append(aid)


class MetadataPrefetchTests(unittest.TestCase):
    def test_missing_series_refreshes_once_then_waits_for_live_metadata(self):
        api = API(state="missing")
        plan = sample_plan()
        eligible = {r["file_id"] for r in plan["groups"][0]["files"]}
        refresh_state = {}
        diagnostics = {}
        self.assertEqual(promote_verified_tv_batch(
            api, plan, eligible, diagnostics=diagnostics,
            refresh_requests=refresh_state, prefetch_missing=True), 0)
        self.assertEqual(diagnostics["proof_gate_reasons"], {"series_not_local": 1})
        self.assertEqual(diagnostics["pending_tv_metadata_aids"], [16027])
        self.assertEqual(diagnostics["target_metadata_refreshes"], 1)
        self.assertEqual(api.refreshes, [16027])
        self.assertTrue(all(r["mode"] == "strong_context"
                            for r in plan["groups"][0]["files"]))
        self.assertEqual(promote_verified_tv_batch(
            api, plan, eligible, refresh_requests=refresh_state,
            prefetch_missing=True), 0)
        self.assertEqual(api.refreshes, [16027])
        api.state = "ready"
        self.assertEqual(promote_verified_tv_batch(
            api, plan, eligible, refresh_requests=refresh_state,
            prefetch_missing=True), 12)
        self.assertEqual(api.refreshes, [16027])
        self.assertTrue(all(r["mode"] == "verified_tv_batch"
                            for r in plan["groups"][0]["files"]))

    def test_no_refresh_without_apply_opt_in(self):
        api = API(state="missing")
        plan = sample_plan()
        eligible = {r["file_id"] for r in plan["groups"][0]["files"]}
        diagnostics = {}
        self.assertEqual(promote_verified_tv_batch(
            api, plan, eligible, diagnostics=diagnostics), 0)
        self.assertEqual(api.refreshes, [])
        self.assertEqual(diagnostics["pending_tv_metadata_aids"], [])

    def test_existing_but_empty_episode_data_can_refresh(self):
        api = API(state="empty")
        plan = sample_plan()
        eligible = {r["file_id"] for r in plan["groups"][0]["files"]}
        diagnostics = {}
        self.assertEqual(promote_verified_tv_batch(
            api, plan, eligible, diagnostics=diagnostics,
            prefetch_missing=True, refresh_requests={}), 0)
        self.assertEqual(diagnostics["proof_gate_reasons"], {"episode_inventory_empty": 1})
        self.assertEqual(api.refreshes, [16027])

    def test_partial_release_does_not_queue_repeated_refreshes(self):
        api = API(state="ready")
        plan = sample_plan()
        plan["groups"][0]["files"] = plan["groups"][0]["files"][:7]
        eligible = {r["file_id"] for r in plan["groups"][0]["files"]}
        diagnostics = {}
        self.assertEqual(promote_verified_tv_batch(
            api, plan, eligible, diagnostics=diagnostics,
            prefetch_missing=True, refresh_requests={}), 0)
        self.assertEqual(diagnostics["proof_gate_reasons"], {"partial_release": 1})
        self.assertEqual(api.refreshes, [])

    def test_same_title_two_anidb_works_never_prefetches(self):
        api = API(state="missing")
        plan = sample_plan()
        plan["groups"][0]["candidates"].append({
            "anidb_id": 16028, "title": "Goblin Slayer II",
            "type": "TV", "season": 2})
        eligible = {r["file_id"] for r in plan["groups"][0]["files"]}
        diagnostics = {}
        self.assertEqual(promote_verified_tv_batch(
            api, plan, eligible, diagnostics=diagnostics,
            prefetch_missing=True, refresh_requests={}), 0)
        self.assertEqual(api.refreshes, [])
        self.assertEqual(diagnostics["title_gate_reasons"]["multiple_exact_tv_work_ids"], 1)

    def test_only_targeted_metadata_triggers_watch_and_worker_retry(self):
        self.assertEqual(retry_delay_for({"awaiting_tv_metadata": 1}), 60)
        self.assertIsNone(retry_delay_for({"submitted": 12, "errors": 0}))
        api = API(state="missing")
        coordinator = object.__new__(Coordinator)
        coordinator.api = api
        coordinator.tv_pending_aids = {16027}
        coordinator.tv_watch_polls = 0
        self.assertFalse(coordinator.poll_target_tv_metadata())
        api.state = "ready"
        self.assertTrue(coordinator.poll_target_tv_metadata())
        self.assertEqual(coordinator.tv_watch_polls, 2)

    def test_target_metadata_watch_stops_after_bounded_probes(self):
        api = API(state="missing")
        coordinator = object.__new__(Coordinator)
        coordinator.api = api
        coordinator.tv_pending_aids = {16027}
        coordinator.tv_watch_polls = 14
        self.assertFalse(coordinator.poll_target_tv_metadata())
        self.assertEqual(coordinator.tv_pending_aids, set())


if __name__ == "__main__":
    unittest.main()
