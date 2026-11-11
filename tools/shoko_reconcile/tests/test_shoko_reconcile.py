"""Regression tests built from synthetic cases and the user's original v1 plan structure.

Do not commit actual user's file inventory to GitHub.
"""
from __future__ import annotations
import json
import tempfile
import unittest
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from matching import clean_release_title, classify_episode, main_title_candidates, similarity, rank_candidates
from catalog import AliasCatalog
from shoko_reconcile import analyze_report, apply, ShokoAPI, export_metadata, _write_private_json


def fixture(folder, items, *, candidates=(), aid=None, mode="review"):
    return {"version":1,"total_unrecognized_at_scan":len(items),"groups":[{
        "folder":folder,"mode":mode,"selected_anidb_id":aid,
        "candidates":[{"anidb_id":c[0],"title":c[1],"score":c[2],"type":"Unknown"} for c in candidates],
        "count":len(items),"files":[{"file_id":i+1,"episode":None,"path":f"{folder}/{name}"} for i,name in enumerate(items)]}]}


class FilenameTests(unittest.TestCase):
    def test_technical_tags_do_not_change_title(self):
        self.assertEqual(clean_release_title("[Gulno] Youjo Senki [BDRip 1920x1080 x264 FLAC]"),"Youjo Senki")
        self.assertEqual(clean_release_title("[Gulno] _Youjo_Senki_ [BDRip 1920x1080 x264 FLAC]"),"Youjo_Senki")
        self.assertEqual(clean_release_title("[Judas] Grand Blue Dreaming (Season 02) [1080p][HEVC x265 10bit]"),"Grand Blue Dreaming Season 02")
        self.assertEqual(clean_release_title("Takt Op. Destiny - AniLibria.TV [WEBRip 1080p HEVC]"),"Takt Op. Destiny")

    def test_title_noise_and_transcription_variants(self):
        self.assertGreater(similarity("Youjo Senki","-youjo-senki-"),0.98)
        self.assertGreater(similarity("Youjo Senki","_Youjo_Senki_"),0.98)
        self.assertGreater(similarity("Youjo Senki","YiujoDenki"),0.65)
        self.assertGreater(similarity("Yuusha Party wo Oidasareta Kiyoubinbou","Yuusha Party o Oidasareta Kiyoubinbou"),0.92)

    def test_regular_episode_formats(self):
        samples={
            "[ReinForce] Youjo Senki - 09 (BDRip 1920x1080 x264 FLAC).mkv":9,
            "Anime_S02_[13]_[HEVC].mkv":13,
            "No Game No Life 01 [BDRip] [HEVC].mkv":1,
            "[Judas] Cyberpunk - S02E10.mkv":10,
            "Tensei Shitara Slime Datta Ken.S02EP24.mkv":24,
            "Ep 01.mkv":1,
            "Anime special 2 [BDRip] [HEVC].mkv":2,
        }
        for filename,number in samples.items():
            with self.subTest(filename=filename):self.assertEqual(classify_episode("Release/"+filename).number,number)

    def test_op_in_title_not_opening_clip(self):
        e=classify_episode("Takt Op. Destiny/Takt_Op_Destiny_[01]_[HEVC].mkv")
        self.assertEqual((e.category,e.number),("Episode",1))

    def test_auxiliary_clips_are_not_invented_episodes(self):
        e=classify_episode("Youjo Senki/Bonus/PV01.mkv")
        self.assertEqual(e.category,"Extra")
        e=classify_episode("Kimetsu/[Judas] Kimetsu no Yaiba - NCOP 02.mkv")
        self.assertEqual(e.category,"Extra")
        e=classify_episode("No Game No Life/Specials/No Game No Life special 2.mkv")
        self.assertEqual((e.category,e.number),("Special",2))

    def test_movie_is_episode_one_with_context(self):
        e=classify_episode("Sword Art Online; Ordinal Scale/Sword_Art_Online_Ordinal_Scale_[Movie]_[BDRip].mkv")
        self.assertEqual((e.category,e.number),("Movie",1))

    def test_franchise_variants_dont_collapse(self):
        self.assertLess(similarity("Go-Toubun no Hanayome~","Go-Toubun no Hanayome"),0.9)
        self.assertLess(similarity("Go-Toubun no Hanayome *","Go-Toubun no Hanayome"),0.9)


class ReportTests(unittest.TestCase):
    def test_exact_prior_preferred_over_heuristic(self):
        f=fixture("OSHI NO KO 3 - AniLiberty [WEB-DL 1080p]",["OSHI_NO_KO_3_[01].mkv"],
                  candidates=[(18901,'"Oshi no Ko" (2026)',1.0),(17449,'"Oshi no Ko"',.91)],aid=18901,mode="exact_title")
        a=analyze_report(f)
        self.assertEqual(a["groups"][0]["files"][0]["target_anidb_id"],18901)

    def test_no_pretense_of_recognizing_extras(self):
        f=fixture("Takt Op. Destiny",["Takt_Op_Destiny_[01].mkv","Takt_Op_Destiny_[02].mkv"],
                  candidates=[(16168,'Takt Op. Destiny',1.0)],aid=16168,mode="exact_title")
        a=analyze_report(f)
        self.assertEqual(a["metrics"]["potential_links_before_api_validation"],2)

    def test_user_file_override_for_special(self):
        f=fixture("No Game No Life",["No Game No Life special 1.mkv"])
        a=analyze_report(f,overrides={"files":{"1":{"anidb_id":9998,"episode":1,"type":"Special"}}})
        row=a["groups"][0]["files"][0]
        self.assertEqual((row["target_anidb_id"],row["episode_type"],row["episode"]),(9998,"Special",1))

    def test_cyrillic_canonical_alias_via_external_catalog(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/"anime.jsonl"
            p.write_text(json.dumps({"version":"fixture"})+"\n"+json.dumps({
                "title":"Tensei Shitara Slime Datta Ken",
                "synonyms":["Про моє переродження в слиз"],
                "sources":["https://anidb.net/anime/13871"],
                "animeSeason":{"year":2018},"episodes":24,"type":"TV"},ensure_ascii=False)+"\n")
            f=fixture("Про моє переродження в слиз",["Про моє переродження в слиз - 01.mkv"])
            a=analyze_report(f,catalog=AliasCatalog(p))
            self.assertEqual(a["groups"][0]["selected_anidb_id"],13871)

    def test_ova_untyped_tv_candidate_must_not_autolink(self):
        f=fixture("5-toubun no Hanayome [OVA] - AniLiberty [WEBRip 1080p]",
                  ["5-toubun_no_Hanayome_[01].mkv"],
                  candidates=[(14247,"Go-Toubun no Hanayome",0.9)])
        report=analyze_report(f)
        self.assertIsNone(report["groups"][0]["selected_anidb_id"])

    def test_part_two_requires_specific_cour_identity(self):
        f=fixture("ReZero (Season 2 Part 2)",
                  ["ReZero S02E14.mkv","ReZero S02E15.mkv"],
                  candidates=[(14792,"Re:Zero (2020)",.96),(15593,"Re:Zero (2021)",.94)])
        report=analyze_report(f)
        self.assertIsNone(report["groups"][0]["selected_anidb_id"])

    def test_second_season_candidates_resolved_from_other_group(self):
        folder="Seijo no Maryoku wa Bannou Desu 2nd Season - AniLibria [WEBRip 1080p]"
        f=fixture(folder,["Seijo_no_Maryoku_wa_Bannou_Desu_[01].mkv"],
                  candidates=[(15720,"Seijo no Maryoku wa Bannou Desu",.88)])
        f["groups"].append({"folder":"Seijo no Maryoku wa Bannou Desu - Release",
            "mode":"exact_title","selected_anidb_id":15720,"candidates":[
                {"anidb_id":17246,"title":"Seijo no Maryoku wa Bannou Desu II","score":.96,"type":"Unknown"}],
            "files":[]})
        report=analyze_report(f)
        self.assertEqual(report["groups"][0]["selected_anidb_id"],17246)

    def test_cour_spinoff_is_not_blindly_linked(self):
        g="Youjo Senki (BDRip 1920x1080 x264 FLAC)"
        f=fixture(g,["[ReinForce] Youjo Senki - 01 (BDRip).mkv","[ReinForce] Youjo Shenki - 01 (BDRip).mkv"],
                  candidates=[(11905,'Youjo Senki',1.0)],aid=11905,mode="exact_title")
        a=analyze_report(f)
        rows=a["groups"][0]["files"]
        self.assertEqual(rows[0]["target_anidb_id"],11905)
        self.assertIsNone(rows[1]["target_anidb_id"])


class ApplyTests(unittest.TestCase):
    class MockAPI:
        def __init__(self, exists=True):self.called=[];self.exists=exists
        def unrecognized(self):return [{"ID":1,"Locations":[{"RelativePath":"Anime/E01.mkv"}]},
                                       {"ID":2,"Locations":[{"RelativePath":"Anime/Extra S01.mkv"}]}]
        def local_series(self,aid):self.called.append(("series",aid));return {"IDs":{"ID":8,"AniDB":123}}
        def available_episodes(self,sid):return {("Episode",1),("Special",1)} if self.exists else set()
        def link(self,*args):self.called.append(("link",*args))

    def plan(self):
        return {"version":2,"groups":[{"folder":"Anime","files":[
            {"file_id":1,"path":"Anime/E01.mkv","target_anidb_id":123,"episode":1,"episode_type":"Episode","mode":"approved_override"},
            {"file_id":2,"path":"Anime/Extra S01.mkv","target_anidb_id":123,"episode":1,"episode_type":"Special","mode":"approved_file_override"}]}]}

    def test_link_and_preserve_special_type(self):
        api=self.MockAPI()
        result=apply(api,self.plan(),delay=0)
        self.assertEqual(result["submitted"],2)
        self.assertIn(("link",2,8,1,"Special"),api.called)

    def test_missing_episode_is_never_written(self):
        api=self.MockAPI(exists=False)
        result=apply(api,self.plan(),delay=0)
        self.assertEqual(result["submitted"],0)
        self.assertFalse(any(c[0]=="link" for c in api.called))

    def test_stale_path_skipped(self):
        api=self.MockAPI()
        plan=self.plan();plan["groups"][0]["files"][0]["path"]="old.mkv"
        result=apply(api,plan,delay=0)
        self.assertEqual(result["submitted"],1)

    def test_limit_is_global(self):
        api=self.MockAPI()
        self.assertEqual(apply(api,self.plan(),delay=0,limit=1)["submitted"],1)

    def test_api_generates_special_prefix(self):
        api=ShokoAPI("http://127.0.0.1:8111","dummy")
        captured=[]
        api.request=lambda method,path,params=None,body=None:captured.append((method,path,body))
        api.link(1,2,3,"Special")
        self.assertEqual(captured[0][2]["RangeStart"],"S3")

    def test_metadata_snapshot_is_per_episode_and_private(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/"private.json"
            _write_private_json(path,{"ok":True})
            self.assertEqual(path.stat().st_mode & 0o777,0o600)
            self.assertTrue(json.loads(path.read_text())["ok"])

if __name__ == "__main__": unittest.main()
