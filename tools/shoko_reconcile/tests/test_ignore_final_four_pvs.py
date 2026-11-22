"""Safe one-command closeout of the final four PVs, with zero media writes."""
from pathlib import Path
import json
import sys
import tempfile
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))

from ignore_final_four_pvs import (
    PVS, PATHS, apply_batch, finish, preflight, read_journal,
)


def fresh():
    return {"schema":1,"attempts":{}}


class API:
    def __init__(self):
        self.ignored=set()
        self.unknown=set(PVS)
        self.paths=dict(PATHS)
        self.xrefs={}
        self.metadata_refs={}
        self.calls=[]
        self.puts=[]
        self.error_fid=None
        self.ignored_not_visible=set()
        self.other_unknown=set()

    def request(self,method,path,params=None,body=None):
        self.calls.append((method,path,params))
        if path=="/File":
            self.assert_unknown_query(method,params)
            fids=sorted((self.unknown | self.other_unknown)-self.ignored)
            return {"Total":len(fids),"List":[{"ID":fid} for fid in fids]}
        if path.startswith("/File/") and path.endswith("/Ignore"):
            assert method=="PUT"
            assert params=={"value":"true"}
            fid=int(path.split("/")[-2])
            assert fid in PVS
            if fid==self.error_fid:
                raise ConnectionError("network response uncertain")
            self.puts.append(fid)
            self.ignored.add(fid)
            return None
        if path.startswith("/File/"):
            assert method=="GET" and params=={"include":"XRefs"}
            fid=int(path.rsplit("/",1)[-1])
            assert fid in PVS
            seriesids=[
                {"SeriesID":{"AniDB":aid},"EpisodeIDs":[{"AniDB":eid}]}
                for aid,eid in self.xrefs.get(fid,[])]
            return {
                "ID":fid,
                "IsIgnored":fid in self.ignored and fid not in self.ignored_not_visible,
                "SeriesIDs":seriesids,
                "MetadataCrossReferences":self.metadata_refs.get(fid,[]),
                "Locations":[{"RelativePath":self.paths[fid]}],
            }
        raise AssertionError(f"Unexpected call {method} {path}")

    @staticmethod
    def assert_unknown_query(method,params):
        assert method=="GET" and params=={
            "include_only":"Unrecognized","pageSize":100,"page":1}


class IgnoreTests(unittest.TestCase):
    def test_allowlist_exact_four_pv_paths(self):
        self.assertEqual(set(PVS),{2994,2997,2999,3020})
        self.assertEqual(len(PATHS),4)
        self.assertTrue(all("PV" in PATHS[fid] for fid in PVS))
        self.assertTrue(all(not p.startswith("/Anime") for p in PATHS.values()))

    def test_dry_run_is_read_only(self):
        api=API()
        report=finish(api,preflight(api,fresh()))
        self.assertEqual(report["counts"],{"ready":4})
        self.assertEqual(report["mode"],"dry_run")
        self.assertEqual(report["unrecognized_after"],4)
        self.assertEqual(api.puts,[])
        self.assertFalse(any(call[0]=="PUT" for call in api.calls))

    def test_exact_four_ignore_all_flags_verified_unrecognized_zero(self):
        api=API()
        journal=fresh()
        saved=[]
        report=apply_batch(api,journal,lambda state:saved.append(
            json.loads(json.dumps(state))),verify_wait=0)
        self.assertEqual(report["mode"],"apply")
        self.assertEqual(report["submitted"],4)
        self.assertEqual(report["verified"],4)
        self.assertEqual(report["unrecognized_after"],0)
        self.assertEqual(report["counts"],{"ignored_verified":4})
        self.assertEqual(set(api.puts),set(PVS))
        self.assertEqual(set(journal["attempts"]),{str(x) for x in PVS})
        self.assertEqual(len(saved),8)
        self.assertTrue(all(x["operation"]=="ignore_true"
                            for x in journal["attempts"].values()))

    def test_an_already_ignored_file_stays_skipped(self):
        api=API()
        api.ignored.add(2994)
        report=apply_batch(api,fresh(),lambda _:None,verify_wait=0)
        self.assertEqual(report["submitted"],3)
        self.assertEqual(report["unrecognized_after"],0)
        self.assertEqual(report["counts"],{"already_ignored":1,"ignored_verified":3})
        self.assertNotIn(2994,api.puts)

    def test_ignored_flag_does_not_hide_other_unknowns_from_report(self):
        api=API()
        api.other_unknown.add(999)
        report=apply_batch(api,fresh(),lambda _:None,verify_wait=0)
        self.assertEqual(report["mode"],"apply")
        self.assertEqual(report["unrecognized_after"],1)
        self.assertEqual(report["unknown_ids_after"],[999])
        self.assertEqual(set(api.puts),set(PVS))

    def test_any_wrong_path_xref_metadata_ref_blocks_all_writes(self):
        for kind in ("path","xref","metadata"):
            with self.subTest(kind=kind):
                api=API()
                if kind=="path":api.paths[2994]="differentfile.mkv"
                if kind=="xref":api.xrefs[2994]=[(11261,1234)]
                if kind=="metadata":api.metadata_refs[2994]=[{"Source":"other"}]
                if kind=="path":
                    with self.assertRaisesRegex(ValueError,"RelativePath changed"):
                        apply_batch(api,fresh(),lambda _:None)
                else:
                    report=apply_batch(api,fresh(),lambda _:None)
                    self.assertEqual(report["mode"],"apply_aborted_preflight")
                self.assertEqual(api.puts,[])

    def test_recognized_without_ignore_not_overwritten(self):
        api=API()
        api.unknown.discard(2999)
        report=apply_batch(api,fresh(),lambda _:None)
        self.assertEqual(report["mode"],"apply_aborted_preflight")
        self.assertEqual(api.puts,[])

    def test_previously_submitted_without_ack_never_sends_duplicate(self):
        api=API()
        journal=fresh()
        journal["attempts"]["2997"]={
            "path":PATHS[2997],"operation":"ignore_true","status":"pending"}
        result=apply_batch(api,journal,lambda _:None,verify_wait=0)
        self.assertEqual(result["mode"],"apply_pending_verification")
        self.assertEqual(result["submitted"],3)
        self.assertNotIn(2997,api.puts)
        self.assertEqual(result["rows"][2997]["status"],
                         "prior_attempt_still_unverified_no_repeat")

    def test_network_error_preserves_attempt_without_retry(self):
        api=API()
        api.error_fid=2997
        journal=fresh()
        report=apply_batch(api,journal,lambda _:None,verify_wait=0)
        self.assertEqual(report["mode"],"apply_interrupted_uncertain")
        self.assertEqual(journal["attempts"]["2997"]["status"],
                         "request_error_uncertain")
        self.assertNotIn(2997,api.puts)
        api.error_fid=None
        api.puts.clear()
        result=apply_batch(api,journal,lambda _:None,verify_wait=0)
        self.assertNotIn(2997,api.puts)
        self.assertEqual(result["mode"],"apply_pending_verification")

    def test_missing_ignored_attribute_or_xref_list_refuses_all(self):
        for key in ("IsIgnored","SeriesIDs","MetadataCrossReferences"):
            api=API()
            old_request=api.request
            def patch(method,path,params=None,body=None):
                result=old_request(method,path,params,body)
                if path=="/File/3020":
                    result.pop(key,None)
                return result
            api.request=patch
            with self.subTest(key=key),self.assertRaises(ValueError):
                apply_batch(api,fresh(),lambda _:None)
            self.assertEqual(api.puts,[])

    def test_corrupt_journal_is_not_used(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/"state.json"
            p.write_text(json.dumps({"schema":1,"attempts":{
                "999":{"path":"fake","operation":"ignore_true"}}}))
            with self.assertRaisesRegex(ValueError,"Invalid"):
                read_journal(p)


if __name__=="__main__":
    unittest.main()
