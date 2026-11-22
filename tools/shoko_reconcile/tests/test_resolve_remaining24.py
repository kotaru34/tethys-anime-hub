"""Safety tests for one-shot 24-file extras resolution without episode guessing."""
from pathlib import Path
import sys
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))

from resolve_remaining24 import (
    PENDING_IDS, DAL_NCED, DAL_SOURCE_TV_EPISODES,
    DAL_SOURCE_SIZES_MIB, DXD_OVA_WORKS, WORK_MAP, CLIP_KINDS,
    YUUSHA_EPISODE, pinned_paths, category_title,
    release_size_proven, choose_clip, run_once,
)

def fresh_state():
    return {"schema":1,"metadata_attempts":{},"xref_attempts":{}}


class FakeShoko:
    def __init__(self):
        self.paths = pinned_paths()
        self.active = set(self.paths)
        self.present = set(WORK_MAP.values())
        self.calls = []
        self.posts = []
        self.bad_path = None
        self.auto_recognize_on_second_read = set()
        self.list_reads = 0
        self.bad_link = None
        self.metadata_auto_create = False
        self.clip_variant_missing = False

    def request(self,method,path,params=None,body=None):
        self.calls.append((method,path))
        if method != "GET" or path != "/File":
            raise AssertionError("Only bounded /File?Unrecognized allowed")
        assert params == {"include_only":"Unrecognized","pageSize":100,"page":1}
        self.list_reads += 1
        if self.list_reads == 2:
            self.active -= self.auto_recognize_on_second_read
        entries = []
        for fid in sorted(self.active):
            mib = DAL_SOURCE_SIZES_MIB[DAL_NCED.index(fid)] \
                  if fid in DAL_NCED else 140.0
            entries.append({
                "ID":fid,"Size":int(mib*1048576),
                "Locations":[{"RelativePath":
                    "changed/file.mkv" if fid == self.bad_path
                    else self.paths[fid]}],
            })
        return {"Total":len(entries),"List":entries}

    def local_series(self,aid):
        self.calls.append(("local_work",aid))
        return {"IDs":{"AniDB":aid,"ID":aid+1000}} if aid in self.present else None

    def refresh_series(self,aid):
        self.calls.append(("metadata_post",aid))
        if aid not in (11184,11844):
            raise AssertionError("Unexpected work creation")
        if self.metadata_auto_create:
            self.present.add(aid)

    def pages(self,path,params,size=500):
        self.calls.append(("episode_list",path))
        assert path.startswith("/Series/") and path.endswith("/Episode")
        assert params["includeDataFrom"] == "AniDB"
        aid = int(path.split("/")[2])-1000
        items = []
        def add(kind,n,eid,title):
            items.append({"AniDB":{
                "ID":eid,"Type":kind,"EpisodeNumber":n,"Title":title}})
        if aid == 8808:
            for n in range(1,10):
                add("Credits",n,880800+n,f"Ending {n}")
        elif aid == 9734:
            add("Credits",1,973400,"Ending")
        elif aid == 10691:
            for n,title in enumerate(("Opening 1a","Opening 1b",
                                       "Ending","Ending 2"),1):
                add("Credits",n,106910+n,title)
        elif aid == 9409:
            for n,title in enumerate(("Opening 1a","Opening 1b",
                                       "Ending 1","Ending 2"),1):
                add("Credits",n,940900+n,title)
        elif aid == 11261:
            add("Trailer",1,112610,"PV")
        elif aid == 11992:
            for n in (1,2):
                add("Trailer",n,119920+n,f"PV {n}")
        elif aid == 16917:
            add("Special",1,256391,YUUSHA_EPISODE["title"])
        elif aid in (11184,11844):
            add("Episode",1,aid*10+1,"Complete OVA")
        if self.clip_variant_missing and aid == 8808:
            items = []
        return items

    def link(self,fid,sid,num,kind):
        self.calls.append(("link",fid,sid,num,kind))
        if fid == self.bad_link:
            raise TimeoutError("simulated network timeout after send")
        self.posts.append((fid,sid,num,kind))

    def unrecognized(self):
        raise AssertionError("No unbounded /File listing")
    def anime_search(self,*args):
        raise AssertionError("No fuzzy search")


class Remaining24Tests(unittest.TestCase):
    def test_exact_cohort_and_types(self):
        paths = pinned_paths()
        self.assertEqual(len(paths),24)
        self.assertEqual(set(paths),PENDING_IDS)
        self.assertEqual(len(CLIP_KINDS),21)
        self.assertEqual(len(DAL_NCED),10)
        self.assertEqual(DAL_SOURCE_TV_EPISODES,(1,2,3,4,5,6,8,10,12,13))
        self.assertEqual(WORK_MAP[DAL_NCED[-1]],9734)
        self.assertEqual(WORK_MAP[3222],16917)
        self.assertEqual({x[0] for x in DXD_OVA_WORKS.values()}, {11184,11844})
        self.assertNotIn(2486,paths)
        self.assertNotIn(2850,paths)
        self.assertNotIn(2909,paths)

    def test_only_exact_title_version_patterns(self):
        for title,kind,answer in [
            ("Opening 1a","Opening",("Opening",1)),
            ("Opening 1b","Opening",("Opening",2)),
            ("Opening","Opening",("Opening",1)),
            ("Ending","Ending",("Ending",1)),
            ("Ending 2","Ending",("Ending",2)),
            ("PV 01","PV",("PV",1)),
            ("PV 02","PV",("PV",2)),
            ("Promotional Video 2","PV",("PV",2)),
            ("CM (0:15)","PV",None),
            ("Ending 9 Extended","Ending",None),
            ("Opening 1a","Ending",None),
        ]:
            with self.subTest(title=title,kind=kind):
                self.assertEqual(category_title(title,kind),answer)

    def test_release_size_evidence_is_bounded(self):
        self.assertTrue(release_size_proven(DAL_NCED[0],int(100.7*1048576)))
        self.assertTrue(release_size_proven(DAL_NCED[-1],int(99.5*1048576)))
        self.assertFalse(release_size_proven(DAL_NCED[0],int(33*1048576)))
        self.assertFalse(release_size_proven(DAL_NCED[0],None))

    def test_default_preview_21_strong_candidates_and_zero_writes(self):
        api=FakeShoko()
        report=run_once(api,fresh_state())
        self.assertEqual(report["counts"]["ready"],21)
        self.assertEqual(report["counts"]["dxd_ova_content_proof_required"],2)
        self.assertEqual(report["counts"]["anidb_clip_variant_missing_or_ambiguous"],1)
        self.assertEqual(report["rows"][3222]["candidate"]["anidb_episode_id"],256391)
        self.assertEqual(report["rows"][3431]["candidate"]["anidb_id"],9734)
        self.assertEqual(report["xref_requests_submitted"],0)
        self.assertEqual(report["metadata_requests_submitted"],0)
        self.assertEqual(api.list_reads,1)
        self.assertEqual(len(api.posts),0)

    def test_operator_apply_only_verified_clips_and_yuusha(self):
        api=FakeShoko()
        state=fresh_state()
        persist=[]
        report=run_once(api,state,apply=True,
                        persist=lambda obj: persist.append((len(obj["metadata_attempts"]),
                                                            len(obj["xref_attempts"]))),
                        sleep=lambda _:None)
        self.assertEqual(report["xref_requests_submitted"],21)
        self.assertEqual(len(api.posts),21)
        self.assertEqual(len(state["xref_attempts"]),21)
        self.assertEqual(report["scope"]["unrecognized_page_reads"],2)
        self.assertEqual(api.list_reads,2)
        self.assertTrue(all(x[0] not in (3209,3206,3020) for x in api.posts))
        self.assertIn((3222,17917,1,"Special"),api.posts)
        self.assertEqual(len(persist),42)
        self.assertEqual(report["counts"]["xref_submitted"],21)

    def test_rerun_is_idempotent_no_duplicate(self):
        api=FakeShoko()
        state=fresh_state()
        run_once(api,state,apply=True,persist=lambda _:None,sleep=lambda _:None)
        api.posts.clear()
        report=run_once(api,state,apply=True,persist=lambda _:None,sleep=lambda _:None)
        self.assertEqual(report["xref_requests_submitted"],0)
        self.assertEqual(api.posts,[])
        self.assertEqual(report["counts"]["previous_xref_attempt_verify_shoko"],21)

    def test_wrong_path_blocks_all_writes(self):
        api=FakeShoko()
        api.bad_path=3435
        with self.assertRaisesRegex(ValueError,"RelativePath drift"):
            run_once(api,fresh_state(),apply=True)
        self.assertEqual(len(api.calls),1)

    def test_unrecognized_count_changes_during_metadata_pause(self):
        api=FakeShoko()
        api.auto_recognize_on_second_read={3222,3435}
        report=run_once(api,fresh_state(),apply=True,persist=lambda _:None)
        self.assertEqual(report["rows"][3222]["status"],"automatically_recognized_skip")
        self.assertEqual(report["rows"][3435]["status"],"automatically_recognized_skip")
        self.assertEqual(report["xref_requests_submitted"],19)
        self.assertNotIn(3222,[p[0] for p in api.posts])

    def test_dxd_metadata_enqueued_once_but_dxd_file_never_linked(self):
        api=FakeShoko()
        api.present -= {11184,11844}
        api.metadata_auto_create = True
        t=[0.0]
        def clock():return t[0]
        def sleeper(n):t[0]+=n
        state=fresh_state()
        report=run_once(api,state,apply=True,persist=lambda _:None,
                        sleep=sleeper,monotonic=clock,max_wait=30)
        self.assertEqual(report["metadata_requests_submitted"],2)
        self.assertEqual(set(state["metadata_attempts"]),{"11184","11844"})
        self.assertEqual(report["rows"][3209]["status"],"dxd_ova_content_proof_required")
        self.assertEqual(report["rows"][3206]["status"],"dxd_ova_content_proof_required")
        api.calls.clear()
        report2=run_once(api,state,apply=True,persist=lambda _:None)
        self.assertEqual(report2["metadata_requests_submitted"],0)
        self.assertFalse(any(x[0]=="metadata_post" for x in api.calls))

    def test_wrong_size_or_sparse_anidb_never_invents_endings(self):
        api=FakeShoko()
        api.clip_variant_missing=True
        report=run_once(api,fresh_state(),apply=True,persist=lambda _:None)
        for fid in DAL_NCED[:-1]:
            self.assertEqual(report["rows"][fid]["status"],
                             "anidb_clip_variant_missing_or_ambiguous")
            self.assertNotIn(fid,[p[0] for p in api.posts])
        self.assertEqual(report["rows"][DAL_NCED[-1]]["status"],"xref_submitted")

    def test_uncertain_response_stops_and_journals_before_retry(self):
        api=FakeShoko()
        api.bad_link=3222
        state=fresh_state()
        report=run_once(api,state,apply=True,persist=lambda _:None)
        self.assertEqual(report["rows"][3222]["status"],"xref_request_error_uncertain")
        self.assertEqual(state["xref_attempts"]["3222"]["outcome"],
                         "request_error_uncertain")
        api.bad_link=None
        api.posts.clear()
        run_once(api,state,apply=True,persist=lambda _:None)
        self.assertNotIn(3222,[p[0] for p in api.posts])


if __name__=="__main__":
    unittest.main()
