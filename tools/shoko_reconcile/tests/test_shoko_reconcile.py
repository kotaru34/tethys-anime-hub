import unittest
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parents[1]))
from shoko_reconcile import extract_title, episode_number, title_similarity, ranked_candidates, group_unrecognized, apply

class ParsingTests(unittest.TestCase):
    def test_anilibria_folder(self):
        self.assertEqual(extract_title('Ragna Crimson - AniLibria.TV [WEBRip 1080p HEVC]'), 'Ragna Crimson')
    def test_bracketed_release_prefix(self):
        self.assertEqual(extract_title('[neko-raws] ReZero kara Hajimeru Isekai Seikatsu - Movie [BDRip 1080p x264 FLAC]'), 'ReZero kara Hajimeru Isekai Seikatsu - Movie')
    def test_season_survives(self):
        self.assertEqual(extract_title('Youkoso Jitsuryoku Shijou Shugi no Kyoushitsu e S4 - AniLiberty [WEB-DL 1080p HEVC]'), 'Youkoso Jitsuryoku Shijou Shugi no Kyoushitsu e S4')
    def test_episodes(self):
        examples = {
           'Ragna_Crimson_[01]_[AniLibria_TV]_[WEBRip_1080p_HEVC].mkv':1,
           'Youkoso_Jitsuryoku_Shijou_Shugi_no_Kyoushitsu_e_S4_[16]_[HEVC].mkv':16,
           '[ReinForce] Youjo Senki - 09 (BDRip 1920x1080 x264 FLAC).mkv':9,
           'Anime S01E13.mkv':13,
           'Anime - OVA.mkv':None,
           'movie.2024.mkv':None,
        }
        for name, episode in examples.items():
            self.assertEqual(episode_number(name), episode, name)
    def test_exact_titles(self):
        self.assertEqual(title_similarity('Ragna Crimson', 'Ragna Crimson'),1.0)
    def test_ordinal_season_aliases(self):
        self.assertEqual(title_similarity('Youkoso Jitsuryoku Shijou Shugi no Kyoushitsu e S3',
                         'Youkoso Jitsuryoku Shijou Shugi no Kyoushitsu e 3rd Season'),1.0)
        self.assertEqual(title_similarity('Anime Season 4', 'Anime 4th Season'),1.0)

    def test_different_season_is_not_auto(self):
        self.assertEqual(ranked_candidates('Anime S4',[{'ID':1,'Title':'Anime S3'}]),[])
    def test_group_paths(self):
        raw=[{'ID':1,'Locations':[{'RelativePath':'Ragna Crimson - AniLibria.TV [WEBRip 1080p HEVC]/Ragna_Crimson_[01].mkv'}]}]
        self.assertEqual(len(group_unrecognized(raw)),1)
    def test_apply_happy_path(self):
        written=[]
        class API:
            def unrecognized(self): return [{'ID':1,'Locations':[{'RelativePath':'Anime/E01.mkv'}]}]
            def local_series(self,n): return {'IDs':{'ID':25,'AniDB':8}}
            def available_episodes(self,n): return {1,2}
            def link(self,*args): written.append(args)
        report={'version':1,'groups':[{'mode':'approved_override','selected_anidb_id':8,
                'folder':'Anime','files':[{'file_id':1,'path':'Anime/E01.mkv','episode':1}]}]}
        self.assertEqual(apply(API(),report,delay=0)['submitted'],1)
        self.assertEqual(written,[(1,25,1)])

    def test_nonexistent_episode_not_linked(self):
        written=[]
        class API:
            def unrecognized(self): return [{'ID':1,'Locations':[{'RelativePath':'Anime/E99.mkv'}]}]
            def local_series(self,n): return {'IDs':{'ID':25,'AniDB':8}}
            def available_episodes(self,n): return {1,2}
            def link(self,*args): written.append(args)
        report={'version':1,'groups':[{'mode':'approved_override','selected_anidb_id':8,
                'folder':'Anime','files':[{'file_id':1,'path':'Anime/E99.mkv','episode':99}]}]}
        self.assertEqual(apply(API(),report,delay=0)['submitted'],0)
        self.assertEqual(written,[])

    def test_apply_wont_write_stale_paths(self):
        class API:
            def unrecognized(self): return [{'ID':1,'Locations':[{'RelativePath':'Anime/a-new-name.mkv'}]}]
            def local_series(self,n): return {'IDs':{'ID':25,'AniDB':8}}
            def available_episodes(self,n): return {1}
            def link(self,*args): raise AssertionError('Must not write')
        report={'version':1,'groups':[{'mode':'approved_override','selected_anidb_id':8,'folder':'Anime','files':[{'file_id':1,'path':'Anime/old.mkv','episode':1}]}]}
        self.assertEqual(apply(API(),report,delay=0)['submitted'],0)

if __name__ == '__main__': unittest.main()
