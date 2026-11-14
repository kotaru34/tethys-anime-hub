"""Low-overhead, fail-closed early TV E01 / RSS continuation proofs."""
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from auto_fallback import keep_safe_rows
from shoko_reconcile import apply
from verified_tv_batch import promote_verified_tv_batch, tv_batch_proof


FOLDER = "Example Series 2 - AniLibria.TV [WEBRip 1080p HEVC]"
AID = 41001
TV = {"anidb_id": AID, "title": "Example Series II", "type": "TV",
      "season": 2, "score": 0.96}


def release(numbers=(1,), candidates=None, extras=()):
    rows = [
        {"file_id": 100 + n,
         "path": f"{FOLDER}/Example_Series_2_[{n:02}]_[HEVC].mkv",
         "episode": n, "source_episode": None,
         "episode_type": "Episode", "target_anidb_id": AID,
         "mode": "strong_context"}
        for n in numbers
    ]
    for i, filename in enumerate(extras, 1):
        rows.append({"file_id": 300 + i, "path": FOLDER + "/" + filename,
                     "episode": None, "source_episode": None,
                     "episode_type": "Extra", "target_anidb_id": None,
                     "mode": "extra"})
    return {"version": 2, "groups": [{
        "folder": FOLDER, "candidates": [TV] if candidates is None else candidates,
        "files": rows}]}


def anchors(*numbers, aid=AID, season=None, other_aid=None):
    ids = {aid}
    if other_aid is not None:
        ids.add(other_aid)
    return {FOLDER: {
        "work_ids": ids,
        "anchors": [(n + 1000, aid, n, season) for n in numbers]
    }}


class FakeAPI:
    def __init__(self, rows, *, ready=True, count=12):
        self.rows = rows
        self.ready = ready
        self.count = count
        self.linked = []
        self.reads = 0
        self.refreshed = []

    def local_series(self, aid):
        self.reads += 1
        return {"IDs": {"ID": 222, "AniDB": aid}} if self.ready and aid == AID else None

    def available_episodes(self, sid):
        self.reads += 1
        assert sid == 222
        return {("Episode", n) for n in range(1, self.count + 1)}

    def unrecognized(self):
        return [{"ID": row["file_id"],
                 "Locations": [{"RelativePath": row["path"]}]}
                for row in self.rows]

    def link(self, file_id, series_id, ep, kind):
        self.linked.append((file_id, series_id, ep, kind))

    def refresh_series(self, aid):
        self.refreshed.append(aid)

    def pages(self, *args, **kwargs):
        raise AssertionError("Early RSS path must reuse existing sibling index")


class EarlyRSSProofTests(unittest.TestCase):
    def test_exact_e01_links_on_first_release_with_no_prior_siblings(self):
        p = release()
        api = FakeAPI(p["groups"][0]["files"])
        eligible = {101}
        diag = {}
        promoted = promote_verified_tv_batch(
            api, p, eligible, diagnostics=diag, sibling_reference={})
        self.assertEqual(promoted, 1)
        self.assertEqual(diag["early_tv_episodes_promoted"], 1)
        safe, rejected = keep_safe_rows(p, eligible)
        self.assertEqual(rejected, 0)
        self.assertEqual(apply(api, safe, delay=0, sibling_reference={})["submitted"], 1)
        self.assertEqual(api.linked, [(101, 222, 1, "Episode")])
        # Only group-level discovery and mandatory write revalidation read
        # target metadata. No additional search, scan, or periodic timer.
        self.assertLessEqual(api.reads, 6)

    def test_single_ep02_after_existing_ep01_needs_one_cached_anchor(self):
        p = release((2,))
        api = FakeAPI(p["groups"][0]["files"])
        ref = anchors(1)
        self.assertEqual(promote_verified_tv_batch(
            api, p, {102}, sibling_reference=ref), 1)
        safe, _ = keep_safe_rows(p, {102})
        self.assertEqual(apply(api, safe, delay=0,
                               sibling_reference=ref)["submitted"], 1)
        self.assertEqual(api.linked, [(102, 222, 2, "Episode")])

    def test_ep03_after_ep02_and_burst_ep03_ep04(self):
        p = release((3, 4))
        api = FakeAPI(p["groups"][0]["files"])
        ref = anchors(1, 2)
        self.assertEqual(promote_verified_tv_batch(
            api, p, {103, 104}, sibling_reference=ref), 2)
        safe, rejected = keep_safe_rows(p, {103, 104})
        self.assertEqual(rejected, 0)
        self.assertEqual(apply(api, safe, delay=0,
                               sibling_reference=ref)["submitted"], 2)
        self.assertEqual([r[2] for r in api.linked], [3, 4])

    def test_ep02_rejects_missing_anchor_before_any_metadata_calls(self):
        p = release((2,))
        api = FakeAPI(p["groups"][0]["files"])
        diag = {}
        self.assertEqual(promote_verified_tv_batch(
            api, p, {102}, sibling_reference={}, diagnostics=diag), 0)
        self.assertEqual(api.reads, 0)
        self.assertEqual(diag["proof_gate_reasons"],
                         {"adjacent_linked_tv_anchor_missing_or_mixed": 1})

    def test_ep02_without_cached_index_never_triggers_full_xref_scan(self):
        p = release((2,))
        api = FakeAPI(p["groups"][0]["files"])
        self.assertEqual(promote_verified_tv_batch(api, p, {102}), 0)
        self.assertEqual(api.reads, 0)
        self.assertIsNone(tv_batch_proof(api, p["groups"][0]))

    def test_wrong_or_mixed_work_anchor_is_rejected(self):
        for ref in (anchors(1, aid=62001),
                    anchors(1, other_aid=62002)):
            p = release((2,))
            api = FakeAPI(p["groups"][0]["files"])
            self.assertEqual(promote_verified_tv_batch(
                api, p, {102}, sibling_reference=ref), 0)
            self.assertEqual(api.reads, 0)

    def test_nonadjacent_or_wrong_season_anchors_fail(self):
        for ref in (anchors(1), anchors(2, season=1)):
            p = release((4,))
            api = FakeAPI(p["groups"][0]["files"])
            self.assertEqual(promote_verified_tv_batch(
                api, p, {104}, sibling_reference=ref), 0)
            self.assertEqual(api.reads, 0)

    def test_identical_anidb_titles_remain_ambiguous_without_metadata_fetch(self):
        p = release(candidates=[TV, {**TV, "anidb_id": 41002}])
        api = FakeAPI(p["groups"][0]["files"])
        self.assertEqual(promote_verified_tv_batch(
            api, p, {101}, sibling_reference={}), 0)
        self.assertEqual(api.reads, 0)

    def test_early_ova_and_bonus_never_linked_as_tv(self):
        p = release(extras=("Bonus/NCOP.mkv",))
        p["groups"][0]["files"].append({
            "file_id": 999, "path": FOLDER + "/Example_Series_2_-_02_(OVA_1).mkv",
            "episode": 1, "source_episode": None, "episode_type": "Special",
            "target_anidb_id": None, "mode": "episode_review"})
        api = FakeAPI(p["groups"][0]["files"])
        self.assertEqual(promote_verified_tv_batch(
            api, p, {101, 301, 999}, sibling_reference={}), 1)
        safe, reviewed = keep_safe_rows(p, {101, 301, 999})
        self.assertEqual((reviewed, len(safe["groups"][0]["files"])), (2, 1))
        self.assertEqual(apply(api, safe, delay=0,
                               sibling_reference={})["submitted"], 1)

    def test_bare_episode13_without_existing_e12_anchor_cannot_be_guessed(self):
        p = release((13,))
        api = FakeAPI(p["groups"][0]["files"])
        self.assertEqual(promote_verified_tv_batch(
            api, p, {113}, sibling_reference={}), 0)
        self.assertEqual(api.linked, [])
        self.assertEqual(api.reads, 0)

    def test_missing_metadata_only_targeted_refresh_once(self):
        p = release()
        api = FakeAPI(p["groups"][0]["files"], ready=False)
        requests = {}
        d = {}
        for i in range(2):
            self.assertEqual(promote_verified_tv_batch(
                api, p, {101}, sibling_reference={}, diagnostics=d,
                prefetch_missing=True, refresh_requests=requests), 0)
        self.assertEqual(api.refreshed, [AID])
        self.assertEqual(d["pending_tv_metadata_aids"], [AID])
        self.assertEqual(p["groups"][0]["files"][0]["mode"], "strong_context")

    def test_forged_cached_anchor_fails_again_at_write_boundary(self):
        p = release((2,))
        api = FakeAPI(p["groups"][0]["files"])
        self.assertEqual(promote_verified_tv_batch(
            api, p, {102}, sibling_reference=anchors(1)), 1)
        safe, _ = keep_safe_rows(p, {102})
        result = apply(api, safe, delay=0, sibling_reference={})
        self.assertEqual(result["submitted"], 0)
        self.assertEqual(result["deferred_by_reason"],
                         {"verified_tv_batch_live_proof_missing": 1})
        self.assertEqual(api.linked, [])


if __name__ == "__main__":
    unittest.main()
