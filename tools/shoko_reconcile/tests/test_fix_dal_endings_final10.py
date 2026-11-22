"""Regression for corrected Date A Live NCED variants, exact live XRefs and journal."""
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))

from fix_dal_endings_final10 import (
    AID, SID, ENDINGS, UNRESOLVED, EXPECTED_PATHS,
    apply_safe, check_episode_inventory, current_refs, ending_size_matches,
    inspection, load_state, finalize,
)

def fresh_state():
    return {"schema":1,"attempts":{}}


class FakeShoko:
    def __init__(self):
        self.calls=[]
        self.posts=[]
        self.files={}
        self.wrong_file_path=None
        self.bad_episode=None
        self.bad_link=None
        self.return_unverified=None
        self.override_credit=None
        self.malform_xrefs=False
        self.unrecognized=set()
        self.credits={1:(148985,"Opening")}
        for ordinal,fid,num,eid,title,mib,old_id in ENDINGS:
            self.credits[num]=(eid,title)
            self.files[fid]={
                "ID":fid,"Size":int(mib*1048576),
                "Locations":[{"RelativePath":EXPECTED_PATHS[fid]}],
                "SeriesIDs":[] if old_id is None and ordinal in (2,7,8,9)
                            else [{"SeriesID":{"ID":SID,"AniDB":AID},
                                   "EpisodeIDs":[{"AniDB":old_id or eid}]}],
            }
            if ordinal in (2,7,8,9):
                self.unrecognized.add(fid)
        for fid in UNRESOLVED:
            self.unrecognized.add(fid)
            self.files[fid]={
                "ID":fid,"Size":200000000,
                "Locations":[{"RelativePath":EXPECTED_PATHS[fid]}],
                "SeriesIDs":[]}

    def request(self,method,path,params=None,body=None):
        self.calls.append((method,path,params))
        assert method=="GET"
        if path=="/File":
            assert params=={
                "include_only":"Unrecognized","pageSize":100,"page":1}
            return {"Total":len(self.unrecognized),"List":[
                {"ID":fid} for fid in sorted(self.unrecognized)]}
        if path.startswith("/File/"):
            assert params=={"include":"XRefs"}
            fid=int(path.split("/")[-1])
            data=json.loads(json.dumps(self.files[fid]))
            if fid==self.wrong_file_path:
                data["Locations"][0]["RelativePath"]="WRONG/file.mkv"
            if self.malform_xrefs and fid==3432:
                data.pop("SeriesIDs",None)
            if fid==self.return_unverified and any(post[0]==fid for post in self.posts):
                data["SeriesIDs"]=[]
            return data
        raise AssertionError(f"Unexpected endpoint {path}")

    def local_series(self,aid):
        self.calls.append(("WORK",aid,None))
        assert aid==AID
        return {"IDs":{"ID":SID,"AniDB":AID}}

    def pages(self,path,params,size=500):
        self.calls.append(("PAGES",path,None))
        assert path==f"/Series/{SID}/Episode"
        assert params["includeDataFrom"]=="AniDB"
        entries=[]
        for number,(eid,title) in self.credits.items():
            if number==self.bad_episode:
                eid+=77
            entries.append({"AniDB":{
                "ID":eid,"Type":"Credits","EpisodeNumber":number,
                "Title":title}})
        return entries

    def link(self,fid,sid,episode,kind):
        self.calls.append(("POST",fid,None))
        if fid==self.bad_link:
            raise TimeoutError("uncertain network response")
        assert sid==SID and kind=="Credits"
        eid,_=self.credits[episode]
        self.files[fid]["SeriesIDs"]=[{
            "SeriesID":{"ID":SID,"AniDB":AID},
            "EpisodeIDs":[{"AniDB":eid}]}]
        self.unrecognized.discard(fid)
        self.posts.append((fid,episode,eid))

    def unrecognized(self):
        raise AssertionError("Do not use unbounded listing")


class Final10Tests(unittest.TestCase):
    def test_exact_nine_credits_order_and_3_protected_corrections(self):
        self.assertEqual(len(ENDINGS),9)
        self.assertEqual(len(UNRESOLVED),6)
        self.assertEqual({r[1] for r in ENDINGS},{3435,3430,3433,3432,3437,
                                                  3438,3429,3439,3434})
        self.assertEqual({r[1] for r in ENDINGS if r[-1] is not None},
                         {3432,3437,3438})
        self.assertEqual({r[1] for r in ENDINGS if r[-1] is None
                          and r[0] in (2,7,8,9)},
                         {3430,3429,3439,3434})
        self.assertEqual([(r[2],r[4]) for r in ENDINGS],[
            (2,"Ending 1"),(3,"Ending 2a"),(4,"Ending 3"),
            (5,"Ending 2b"),(6,"Ending 4"),(7,"Ending 5"),
            (8,"Ending 2c"),(9,"Ending 2d"),(10,"Ending 6")])

    def test_default_preview_one_bounded_listing_nine_exact_file_reads(self):
        api=FakeShoko()
        rows,others=inspection(api,fresh_state())
        self.assertEqual(
            dict(__import__("collections").Counter(r["status"] for r in rows.values())),
            {"already_correct":2,"ready_new_link":4,"ready_correction":3})
        self.assertEqual(len(others),6)
        self.assertEqual(len([x for x in api.calls if x[1]=="/File"]),1)
        self.assertEqual(len([x for x in api.calls if isinstance(x[1], str) and x[1].startswith("/File/")]),15)
        self.assertFalse(any(x[0]=="POST" for x in api.calls))

    def test_apply_updates_exactly_7_and_verifies_each(self):
        api=FakeShoko()
        st=fresh_state()
        saves=[]
        result=apply_safe(api,st,lambda s:saves.append(json.loads(json.dumps(s))))
        self.assertEqual(result["mode"],"apply")
        self.assertEqual(result["submitted"],7)
        self.assertEqual(result["verified_after_write"],7)
        self.assertEqual(result["counts"],{
            "already_correct":2,"xref_verified_new":4,"xref_verified_corrected":3})
        self.assertEqual(len(saves),14)
        self.assertEqual(len(st["attempts"]),7)
        for ordinal,fid,num,eid,_,_,_ in ENDINGS:
            self.assertEqual(current_refs(api.files[fid]),[(AID,eid)])
        self.assertEqual([x[:2] for x in api.posts],
            [(3430,3),(3432,5),(3437,6),(3438,7),
             (3429,8),(3439,9),(3434,10)])

    def test_repeat_after_apply_does_not_modify_anything(self):
        api=FakeShoko()
        st=fresh_state()
        apply_safe(api,st,lambda _:None)
        api.posts.clear()
        result=apply_safe(api,st,lambda _:self.fail("No additional journal"))
        self.assertEqual(result["submitted"],0)
        self.assertEqual(result["counts"],{"already_correct":9})
        self.assertEqual(api.posts,[])

    def test_different_actual_xref_blocks_entire_batch(self):
        for id in (3432,3437,3438):
            with self.subTest(id=id):
                api=FakeShoko()
                api.files[id]["SeriesIDs"][0]["EpisodeIDs"][0]["AniDB"]=99999
                result=apply_safe(api,fresh_state(),lambda _:None)
                self.assertEqual(result["mode"],
                                 "apply_aborted_unexpected_existing_xrefs")
                self.assertEqual(result["submitted"],0)
                self.assertEqual(api.posts,[])

    def test_api_must_include_real_xrefs_not_fake_includeXRefs(self):
        api=FakeShoko()
        api.malform_xrefs=True
        with self.assertRaisesRegex(ValueError,"missing SeriesIDs"):
            inspection(api,fresh_state())
        self.assertFalse(api.posts)

    def test_wrong_release_path_blocks_writes(self):
        api=FakeShoko()
        api.wrong_file_path=3434
        with self.assertRaisesRegex(ValueError,"relative path"):
            apply_safe(api,fresh_state(),lambda _:None)
        self.assertFalse(api.posts)

    def test_changed_local_credits_id_or_title_blocks_all(self):
        for issue in (5,8):
            api=FakeShoko()
            api.bad_episode=issue
            with self.assertRaisesRegex(ValueError,"AniDB Credits C"):
                apply_safe(api,fresh_state(),lambda _:None)
            self.assertFalse(api.posts)

    def test_wrong_file_size_blocks_whole_batch(self):
        api=FakeShoko()
        api.files[3430]["Size"]=1000
        result=apply_safe(api,fresh_state(),lambda _:None)
        self.assertEqual(result["mode"],
                         "apply_aborted_unexpected_existing_xrefs")
        self.assertEqual(result["submitted"],0)
        self.assertFalse(api.posts)

    def test_timeout_records_attempt_before_return_and_never_retries(self):
        api=FakeShoko()
        api.bad_link=3432
        st=fresh_state()
        snapshots=[]
        result=apply_safe(api,st,
                          lambda x:snapshots.append(json.loads(json.dumps(x))))
        self.assertEqual(result["mode"],"apply_interrupted_uncertain")
        self.assertEqual(result["submitted"],1)
        self.assertEqual(st["attempts"]["3432"]["outcome"],
                         "request_error_uncertain")
        self.assertEqual(snapshots[-2]["attempts"]["3432"]["outcome"],
                         "dispatch_uncertain")
        api.bad_link=None
        api.posts.clear()
        result=apply_safe(api,st,lambda _:None)
        self.assertNotIn(3432,[row[0] for row in api.posts])
        self.assertEqual(result["rows"][3432]["status"],
                         "previously_attempted_inspect_manually")

    def test_unverified_post_aborts_and_does_not_repeat(self):
        api=FakeShoko()
        api.return_unverified=3432
        st=fresh_state()
        result=apply_safe(api,st,lambda _:None)
        self.assertEqual(result["mode"],"apply_interrupted_unverified")
        self.assertEqual(st["attempts"]["3432"]["outcome"],"submitted_unverified")
        self.assertEqual(result["verified_after_write"],1)

    def test_journal_rejects_foreign_aniDB_work(self):
        with tempfile.TemporaryDirectory() as tmp:
            f=Path(tmp)/"state.json"
            f.write_text(json.dumps({"schema":1,"attempts":{"1":{}}}))
            with self.assertRaisesRegex(ValueError,"corrupt"):
                load_state(f)


if __name__=="__main__":
    unittest.main()
