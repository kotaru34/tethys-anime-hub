"""Two carefully scoped DxD OVA XRefs; PVs never modified."""
import json
from pathlib import Path
import sys
import tempfile
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))

from link_final_dxd_two_ova import (
    OTHER_PVS, PATHS, TARGETS, apply, inspect, journal_read,
    summarize,
)

def state():
    return {"schema":1,"attempts":{}}


class FakeShoko:
    def __init__(self):
        self.paths=dict(PATHS)
        self.refs={fid:[] for fid in TARGETS}
        self.unknown=set(TARGETS)|set(OTHER_PVS)
        self.present={11184,11844}
        self.wrong_path=None
        self.wrong_episode=None
        self.bad_post=None
        self.calls=[]
        self.posts=[]
        self.delayed=set()
        self.fake_stale={}
        self.elapsed_reads={}

    def request(self, method, path, params=None, body=None):
        self.calls.append((method,path))
        if method!="GET":
            raise AssertionError("Only bounded reads are allowed")
        if path=="/File":
            assert params=={
                "include_only":"Unrecognized","pageSize":100,"page":1}
            return {"Total":len(self.unknown),"List":[
                {"ID":fid} for fid in sorted(self.unknown)]}
        if path.startswith("/File/"):
            assert params=={"include":"XRefs"}
            fid=int(path.split("/")[-1])
            source=self.refs[fid]
            if self.elapsed_reads.get(fid,0)>0 and fid in self.fake_stale:
                self.elapsed_reads[fid]-=1
                source=self.fake_stale[fid]
            return {
                "ID":fid,"Locations":[{"RelativePath":
                    "CHANGED.mkv" if self.wrong_path==fid else self.paths[fid]}],
                "SeriesIDs":[{"SeriesID":{"AniDB":aid},
                              "EpisodeIDs":[{"AniDB":ep}]} for aid,ep in source],
            }
        raise AssertionError(path)

    def local_series(self,aid):
        self.calls.append(("GET_SERIES",aid))
        return {"IDs":{"ID":aid+1000,"AniDB":aid}} if aid in self.present else None

    def pages(self,path,params,size):
        self.calls.append(("GET_EPISODES",path))
        aid=int(path.split("/")[2])-1000
        assert params["includeDataFrom"]=="AniDB"
        if self.wrong_episode==aid:
            return [{"AniDB":{"ID":1234,"Type":"Episode",
                               "EpisodeNumber":1,"Title":"OVA"}}]
        return [{"AniDB":{"ID":TARGETS[fid][1],"Type":"Episode",
                          "EpisodeNumber":1,"Title":"OVA"}}
                for fid in TARGETS if TARGETS[fid][0]==aid]

    def link(self,fid,sid,num,kind):
        self.calls.append(("POST_XREF",fid))
        if self.bad_post==fid:
            raise TimeoutError("uncertain response")
        aid,eid,expected_kind,n,_=TARGETS[fid]
        assert sid==aid+1000 and kind==expected_kind and num==n
        self.fake_stale[fid]=list(self.refs[fid])
        self.refs[fid]=[(aid,eid)]
        self.unknown.discard(fid)
        self.posts.append(fid)


class FinalOVATests(unittest.TestCase):
    def test_exact_allowlist_two_ovas_four_pvs_never_actionable(self):
        self.assertEqual(set(TARGETS),{3209,3206})
        self.assertEqual(set(OTHER_PVS),{2994,2997,2999,3020})
        self.assertTrue(set(TARGETS).isdisjoint(OTHER_PVS))
        self.assertEqual(TARGETS[3209],(11184,161394,"Episode",1,"OVA"))
        self.assertEqual(TARGETS[3206],(11844,167801,"Episode",1,"OVA"))
        self.assertEqual(set(PATHS),set(TARGETS))

    def test_read_only_preflight_no_post(self):
        api=FakeShoko()
        result=summarize(inspect(api,state()))
        self.assertEqual(result["counts"],{"ready":2})
        self.assertEqual(result["total_unrecognized_start"],6)
        self.assertEqual(api.posts,[])
        self.assertEqual(len([x for x in api.calls if x[1]=="/File"]),1)
        self.assertTrue(all(not path.startswith("/Anime")
                            for path in PATHS.values()))

    def test_apply_only_two_unique_ova_xrefs_and_journal_before_post(self):
        api=FakeShoko()
        journal=state()
        snapshots=[]
        result=apply(api,journal,lambda x:snapshots.append(
            json.loads(json.dumps(x))),verify_wait=0)
        self.assertEqual(result["mode"],"apply")
        self.assertEqual(result["submitted"],2)
        self.assertEqual(result["verified_after_post"],2)
        self.assertEqual(result["counts"],{"xref_verified":2})
        self.assertEqual(set(api.posts),set(TARGETS))
        self.assertEqual(len(journal["attempts"]),2)
        self.assertEqual(len(snapshots),4)
        for fid in TARGETS:
            self.assertEqual(api.refs[fid],[TARGETS[fid][:2]])
        self.assertEqual(set(api.unknown),set(OTHER_PVS))

    def test_already_linked_files_skip_no_write(self):
        api=FakeShoko()
        api.refs[3206]=[(11844,167801)]
        api.unknown.discard(3206)
        report=apply(api,state(),lambda _:None,verify_wait=0)
        self.assertEqual(report["counts"],{
            "already_correct":1,"xref_verified":1})
        self.assertEqual(api.posts,[3209])

    def test_wrong_path_or_episode_or_work_blocks_all_posts(self):
        for case in ("path","episode","work"):
            with self.subTest(case=case):
                api=FakeShoko()
                if case=="path":api.wrong_path=3206
                if case=="episode":api.wrong_episode=11184
                if case=="work":api.present.remove(11844)
                try:
                    result=apply(api,state(),lambda _:None,verify_wait=0)
                    self.assertEqual(result["mode"],"apply_aborted_preflight")
                except ValueError as exc:
                    self.assertIn("relative path",str(exc))
                self.assertEqual(api.posts,[])

    def test_nonempty_unrelated_xref_blocks_all(self):
        api=FakeShoko()
        api.refs[3209]=[(11184,98765)]
        report=apply(api,state(),lambda _:None,verify_wait=0)
        self.assertEqual(report["mode"],"apply_aborted_preflight")
        self.assertEqual(api.posts,[])

    def test_previous_journal_does_not_allow_retry_even_if_no_link_seen(self):
        api=FakeShoko()
        st=state()
        st["attempts"]["3206"]={
            "aid":11844,"eid":167801,"outcome":"unverified_pending"}
        report=apply(api,st,lambda _:None,verify_wait=0)
        self.assertEqual(report["mode"],"apply_pending_confirmation")
        self.assertEqual(report["submitted"],1)
        self.assertEqual(api.posts,[3209])
        self.assertEqual(report["rows"][3206]["status"],
                         "previous_attempt_unverified_no_retry")

    def test_delayed_visibility_does_not_issue_duplicate_post(self):
        api=FakeShoko()
        api.elapsed_reads[3206]=2
        t=[0]
        def clock():return t[0]
        def sleep(n):t[0]+=n
        report=apply(api,state(),lambda _:None,verify_wait=5,
                     sleep=sleep,clock=clock)
        self.assertEqual(report["mode"],"apply")
        self.assertEqual(report["verified_after_post"],2)
        self.assertEqual(api.posts.count(3206),1)
        self.assertEqual(t[0],2)

    def test_network_error_journal_prevents_repeated_post(self):
        api=FakeShoko()
        api.bad_post=3206
        st=state()
        saved=[]
        report=apply(api,st,lambda x:saved.append(
            json.loads(json.dumps(x))),verify_wait=0)
        self.assertEqual(report["mode"],"apply_interrupted_uncertain")
        self.assertEqual(st["attempts"]["3206"]["outcome"],
                         "network_error_uncertain")
        api.bad_post=None
        api.posts.clear()
        report=apply(api,st,lambda _:None,verify_wait=0)
        self.assertNotIn(3206,api.posts)
        self.assertEqual(report["rows"][3206]["status"],
                         "previous_attempt_unverified_no_retry")

    def test_previous_journal_wrong_target_blocks_all(self):
        api=FakeShoko()
        st=state()
        st["attempts"]["3209"]={"aid":11844,"eid":167801}
        report=apply(api,st,lambda _:None,verify_wait=0)
        self.assertEqual(report["mode"],"apply_aborted_preflight")
        self.assertEqual(api.posts,[])

    def test_journal_not_allowed_to_target_non_ova_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/"state.json"
            p.write_text(json.dumps({
                "schema":1,"attempts":{"2994":{"eid":4}}}))
            with self.assertRaisesRegex(ValueError,"Invalid"):
                journal_read(p)


if __name__=="__main__":
    unittest.main()
