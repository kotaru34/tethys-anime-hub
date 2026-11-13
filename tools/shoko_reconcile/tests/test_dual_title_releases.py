"""Live-plan regression: bilingual release folders and episode revision suffixes."""
import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from matching import main_title_candidates, parenthetical_title_variants, classify_episode
from refinements import _title_candidate_confidence
from shoko_reconcile import prepare


class DummyAPI:
    def __init__(self, folder, episode_name, anidb_id, canonical, aliases):
        self.folder = folder
        self.episode_name = episode_name
        self.anidb_id = anidb_id
        self.canonical = canonical
        self.aliases = aliases
        self.queries = []

    def unrecognized(self):
        return [{"ID": 9999, "Locations": [{
            "RelativePath": f"{self.folder}/{self.episode_name}"
        }]}]

    def pages(self, path):
        assert path == "/File", path
        yield from self.unrecognized()

    def anime_search(self, query):
        self.queries.append(query)
        if any(alias.casefold() in query.casefold() for alias in self.aliases):
            return [{"ID": self.anidb_id, "Title": self.canonical,
                     "Type": "TV", "Titles": [{"Name": name} for name in self.aliases]}]
        return []


class DualTitleReleaseTests(unittest.TestCase):
    def test_parenthetical_alternatives_and_non_title_metadata(self):
        folder = "Mahoutsukai Reimeiki (The Dawn of the Witch) (Season 1) [1080p]"
        self.assertEqual(parenthetical_title_variants(folder),
                         ["Mahoutsukai Reimeiki", "The Dawn of the Witch"])
        self.assertEqual(parenthetical_title_variants(
            "Kono Kaisha [AMZN (by VARYG)] [RUS(int), JAP+SUB]"), [])
        self.assertEqual(parenthetical_title_variants(
            "Series Title (2026) (Season 2) [1080p]"), [])

    def test_revision_suffix_not_part_of_anime_title(self):
        folder = "Kakkou no Iinazuke (A Couple of Cuckoos) (Season 1)"
        files = [{"path": f"{folder}/[Judas] Kakkou no Iinazuke - S01E11v2.mkv"}]
        queries = main_title_candidates(folder, files)
        self.assertIn("Kakkou no Iinazuke", queries)
        self.assertIn("A Couple of Cuckoos", queries)
        self.assertFalse(any("v2" in query.casefold() for query in queries))
        ep = classify_episode(files[0]["path"], group=folder)
        self.assertEqual((ep.season, ep.number), (1, 11))

    def test_alternate_english_title_reaches_correct_shoko_work(self):
        folder = "Mahoutsukai Reimeiki (The Dawn of the Witch) (Season 1)"
        api = DummyAPI(
            folder, "[Judas] Mahoutsukai Reimeiki - S01E01.mkv",
            16280, "The Dawn of the Witch", ["The Dawn of the Witch"])
        plan = prepare(api, overrides={}, catalog=None)
        self.assertIn("The Dawn of the Witch", api.queries)
        group = plan["groups"][0]
        self.assertEqual(group["selected_anidb_id"], 16280)
        self.assertEqual(group["files"][0]["target_anidb_id"], 16280)
        self.assertEqual(group["files"][0]["episode"], 1)

    def test_first_season_exact_alias_is_not_penalized_by_translation(self):
        folder = "Kakkou no Iinazuke (A Couple of Cuckoos) (Season 1)"
        api = DummyAPI(
            folder, "[Judas] Kakkou no Iinazuke - S01E11v2.mkv",
            16188, "Cuckoo no Iinazuke", ["Kakkou no Iinazuke"])
        plan = prepare(api, overrides={}, catalog=None)
        group = plan["groups"][0]
        self.assertEqual(group["selected_anidb_id"], 16188)
        self.assertEqual(group["files"][0]["episode"], 11)
        self.assertEqual(group["files"][0]["target_anidb_id"], 16188)

    def test_season_two_cannot_use_first_season_candidate_even_with_exact_alias(self):
        group = {
            "folder": "Example Story (The Alternate Name) (Season 2)",
            "files": [],
        }
        candidate = {
            "title": "Example Story",
            "matched_alias": "Example Story",
            "season": 1, "type": "TV"
        }
        # The season hard gate is separate from alias similarity.
        from matching import target_season_supported
        group["candidates"] = [dict(candidate, anidb_id=42)]
        row = {"path": group["folder"] + "/Example Story - S02E01.mkv",
               "target_anidb_id": 42, "mode": "strong_context",
               "episode": 1, "episode_type": "Episode"}
        self.assertFalse(target_season_supported(group, row))


if __name__ == "__main__":
    unittest.main()
