"""One-shot resolver: 45 exact IDs, no guesses for ambiguous clips, at-most-once POSTs."""
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from resolve_45_onepass import (
    CREATABLE_AIDS, DAL_EPISODE_FIDS, DAL_NCED_FIDS, DAL_OVA_AID,
    DAL_TV_AID, TARGETED_AIDS, build_expected, episode_index, load_state,
    prepare, snapshot, unique_credit,
)


def state():
    return {"schema": 1, "metadata_attempts": {}, "xref_attempts": {}}


class FakeShoko:
    def __init__(self):
        self.paths, self.targets = build_expected()
        self.active = set(self.paths)
        self.present = set(TARGETED_AIDS)
        self.calls = []
        self.bad_path = None
        self.bad_link = None
        self.missing_episode = None
        self.variant_credits = False
        self.auto_create = False
        self.extra = {}
        self.total_override = None
        self.linked = []

    def request(self, method, path, params=None, body=None):
        self.calls.append((method, path))
        if method != "GET" or path != "/File" or body is not None:
            raise AssertionError("Global read must be one GET /File Unrecognized")
        self.assert_params(params)
        rows = [
            {"ID": fid,
             "Locations": [{"RelativePath": (
                 "WRONG/PATH" if fid == self.bad_path else self.paths[fid])}]}
            for fid in sorted(self.active)
        ] + [{"ID": fid, "Locations": [{"RelativePath": p}]}
             for fid, p in self.extra.items()]
        return {"Total": len(rows) if self.total_override is None
                else self.total_override, "List": rows}

    def assert_params(self, p):
        assert p == {"include_only": "Unrecognized", "pageSize": 100, "page": 1}

    def local_series(self, aid):
        self.calls.append(("GET_WORK", aid))
        if aid not in self.present:
            return None
        return {"IDs": {"ID": aid + 1000, "AniDB": aid}}

    def refresh_series(self, aid):
        self.calls.append(("POST_META", aid))
        assert aid in CREATABLE_AIDS
        if self.auto_create:
            self.present.add(aid)

    def pages(self, path, params, size=500):
        self.calls.append(("GET_EPS", path))
        aid = int(path.split("/")[2]) - 1000
        assert params["includeDataFrom"] == "AniDB"
        raw = []
        ordinary = list(range(1, 13)) if aid == 8808 else [1]
        for n in ordinary:
            if self.missing_episode == (aid, n):
                continue
            raw.append({"AniDB": {
                "ID": aid * 100 + n, "Type": "Episode",
                "EpisodeNumber": n, "Title": f"Episode title {aid}.{n}"}})
        if aid in (11261, 8808):
            credits = [
                ("Opening 1a", 1), ("Opening 1b", 2)] if self.variant_credits else [
                ("Opening", 1)]
            if aid == 11261:
                credits.append(("Ending", 3))
            for title, num in credits:
                raw.append({"AniDB": {"ID": aid * 100 + 50 + num,
                                     "Type": "Credits",
                                     "EpisodeNumber": num, "Title": title}})
        return raw

    def link(self, fid, sid, episode, kind):
        self.calls.append(("POST_XREF", fid, sid, episode, kind))
        if fid == self.bad_link:
            raise TimeoutError("uncertain Shoko network reply")
        self.linked.append((fid, sid, episode, kind))

    def unrecognized(self):
        raise AssertionError("Must use one bounded GET page")

    def anime_search(self, query):
        raise AssertionError("No fuzzy searches allowed")


class OnePassResolverTests(unittest.TestCase):
    def test_exactly_45_files_and_18_confirmable_story_targets(self):
        expected, targets = build_expected()
        self.assertEqual(len(expected), 45)
        self.assertEqual(len(targets), 18)
        self.assertEqual(len(DAL_EPISODE_FIDS), 13)
        self.assertEqual(len(DAL_NCED_FIDS), 10)
        self.assertEqual(targets[DAL_EPISODE_FIDS[11]], (DAL_TV_AID, "Episode", 12))
        self.assertEqual(targets[DAL_EPISODE_FIDS[12]], (DAL_OVA_AID, "Episode", 1))
        self.assertEqual(targets[2955], (DAL_OVA_AID, "Episode", 1))
        self.assertEqual(len(set(expected)), len(expected))
        self.assertNotIn(2486, expected)  # already manually linked Yona
        self.assertNotIn(2909, expected)  # already manually linked Nekopara
        self.assertNotIn(2850, expected)

    def test_dryrun_one_file_enumeration_and_no_post(self):
        api = FakeShoko()
        result = prepare(api, state(), apply=False)
        self.assertEqual(result["total_unrecognized_at_start"], 45)
        self.assertEqual(result["pinned_still_unrecognized"], 45)
        self.assertEqual(result["counts"]["ready"], 21)
        self.assertEqual(result["metadata_requests_submitted"], 0)
        self.assertEqual(result["xref_requests_submitted"], 0)
        self.assertEqual(len([x for x in api.calls if x[1] == "/File"]), 1)
        self.assertFalse(any(x[0].startswith("POST") for x in api.calls))
        self.assertEqual(result["scope"]["media_walks"], 0)
        self.assertEqual(result["scope"]["full_library_scan"], 0)

    def test_apply_only_known_episodes_and_unique_credits(self):
        api = FakeShoko()
        memory = state()
        saved = []
        report = prepare(api, memory, apply=True,
                         persist=lambda s: saved.append(json.loads(json.dumps(s))),
                         sleep=lambda _: None)
        self.assertEqual(report["xref_requests_submitted"], 21)
        self.assertEqual(len(api.linked), 21)
        self.assertEqual(len(memory["xref_attempts"]), 21)
        self.assertEqual(len(saved), 42)
        self.assertEqual(report["counts"]["xref_submitted"], 21)
        self.assertEqual(report["rows"][3426]["candidate"]["anidb_id"], 9734)
        self.assertEqual(report["rows"][3426]["candidate"]["number"], 1)
        self.assertEqual(report["rows"][2955]["candidate"]["anidb_id"], 9734)
        self.assertNotIn(3222, {r[0] for r in api.linked})
        self.assertFalse({3435, 3430, 3433, 3432, 3437, 3438,
                          3429, 3439, 3434, 3431} & {r[0] for r in api.linked})
        self.assertFalse({3209, 3206, 3020, 3005, 3007, 3016, 3017}
                         & {r[0] for r in api.linked})

    def test_rerun_no_second_post_when_shoko_queue_is_delayed(self):
        api = FakeShoko()
        memory = state()
        prepare(api, memory, apply=True, persist=lambda _: None,
                sleep=lambda _: None)
        api.calls.clear()
        report = prepare(api, memory, apply=True, persist=lambda _: None,
                         sleep=lambda _: None)
        self.assertEqual(report["xref_requests_submitted"], 0)
        self.assertEqual(report["counts"]["xref_previously_attempted_verify_in_shoko"],
                         21)
        self.assertFalse(any(x[0].startswith("POST") for x in api.calls))

    def test_metadata_request_create_at_most_once_even_if_async(self):
        api = FakeShoko()
        api.present -= {8808, 9734}
        memory = state()
        report = prepare(api, memory, apply=True, max_wait=0,
                         persist=lambda _: None, sleep=lambda _: None)
        self.assertEqual(report["metadata_requests_submitted"], 2)
        self.assertEqual(set(memory["metadata_attempts"]), {"8808", "9734"})
        self.assertEqual(report["rows"][3423]["status"], "waiting_for_work_metadata")
        self.assertEqual(report["rows"][3426]["status"], "waiting_for_work_metadata")
        api.calls.clear()
        report = prepare(api, memory, apply=True, max_wait=0,
                         persist=lambda _: None, sleep=lambda _: None)
        self.assertEqual(report["metadata_requests_submitted"], 0)
        self.assertFalse(any(x[0] == "POST_META" for x in api.calls))
        api.present.update({8808, 9734})
        api.calls.clear()
        report = prepare(api, memory, apply=True, max_wait=0,
                         persist=lambda _: None, sleep=lambda _: None)
        self.assertEqual(report["metadata_requests_submitted"], 0)
        self.assertEqual(report["rows"][3423]["status"], "xref_submitted")
        self.assertEqual(report["rows"][3426]["status"], "xref_submitted")

    def test_later_auto_created_metadata_completes_in_one_invocation(self):
        api = FakeShoko()
        api.present -= {8808, 9734}
        api.auto_create = True
        ticks = [0.0]
        def clock(): return ticks[0]
        def sleep(seconds): ticks[0] += seconds
        memory = state()
        report = prepare(api, memory, apply=True, max_wait=30,
                         persist=lambda _: None, sleep=sleep, monotonic=clock)
        self.assertEqual(report["metadata_requests_submitted"], 2)
        self.assertEqual(report["xref_requests_submitted"], 21)
        self.assertEqual(report["work_status"]["8808"]["status"], "present")

    def test_credits_variants_never_inferred_by_file_ordinal(self):
        api = FakeShoko()
        api.variant_credits = True
        result = prepare(api, state())
        self.assertEqual(result["rows"][3436]["status"],
                         "credits_not_uniquely_proven_in_anidb")
        self.assertEqual(result["rows"][2993]["status"],
                         "credits_not_uniquely_proven_in_anidb")
        self.assertEqual(result["rows"][2995]["status"], "ready")
        self.assertEqual(result["rows"][3016]["status"],
                         "extra_variant_or_pv_needs_clip_identity")

    def test_unchanged_file_path_required_before_any_write(self):
        api = FakeShoko()
        api.bad_path = 3423
        with self.assertRaisesRegex(ValueError, "RelativePath changed"):
            prepare(api, state(), apply=True, persist=lambda _: None)
        self.assertEqual(len(api.calls), 1)
        self.assertFalse(api.linked)

    def test_strict_page_cap_no_early_post(self):
        api = FakeShoko()
        api.total_override = 101
        with self.assertRaises(ValueError):
            prepare(api, state(), apply=True, persist=lambda _: None)
        self.assertFalse(any(x[0].startswith("POST") for x in api.calls))

    def test_missing_anidb_episode_never_linked_as_another_number(self):
        api = FakeShoko()
        api.missing_episode = (8808, 6)
        report = prepare(api, state(), apply=True, persist=lambda _: None)
        file_id = DAL_EPISODE_FIDS[5]
        self.assertEqual(report["rows"][file_id]["status"],
                         "missing_or_ambiguous_anidb_episode")
        self.assertNotIn(file_id, [x[0] for x in api.linked])

    def test_uncertain_link_post_recorded_before_retry(self):
        api = FakeShoko()
        first_id = sorted(api.paths)[0]
        api.bad_link = first_id
        memory = state()
        report = prepare(api, memory, apply=True, persist=lambda _: None)
        self.assertEqual(report["rows"][first_id]["status"],
                         "xref_request_error_uncertain")
        self.assertEqual(memory["xref_attempts"][str(first_id)]["outcome"],
                         "request_error_uncertain")
        api.bad_link = None
        api.calls.clear()
        prepare(api, memory, apply=True, persist=lambda _: None)
        self.assertNotIn(first_id, [x[1] for x in api.calls if x[0] == "POST_XREF"])

    def test_reject_foreign_journal_ids(self):
        from tempfile import TemporaryDirectory
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "state.json"
            path.write_text(json.dumps({
                "schema": 1, "metadata_attempts": {"888888": {}},
                "xref_attempts": {}}))
            with self.assertRaises(ValueError):
                load_state(path)


if __name__ == "__main__":
    unittest.main()
