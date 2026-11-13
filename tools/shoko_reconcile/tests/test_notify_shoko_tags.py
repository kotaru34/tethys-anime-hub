"""Offline tests for qBittorrent's %G tag-gated Shoko hook."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / "notify-shoko.sh"


class HookTagFilteringTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.state = self.root / "state"
        self.state.mkdir()
        fake_bin = self.root / "bin"
        fake_bin.mkdir()
        # Prevent a real worker (and HTTP call) in offline filtering tests.
        (fake_bin / "nohup").write_text("#!/bin/sh\nexit 0\n")
        (fake_bin / "nohup").chmod(0o755)
        self.env = os.environ.copy()
        self.env.update({
            "SHOKO_NOTIFY_STATE_DIR": str(self.state),
            "PATH": f"{fake_bin}:{self.env['PATH']}",
        })

    def call(self, *args):
        proc = subprocess.run(
            ["bash", str(SCRIPT), *args],
            env=self.env, capture_output=True, text=True, timeout=3,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        state_file = self.state / "pending"
        return state_file.read_text() if state_file.exists() else None

    def test_only_exact_anime_tag_is_accepted(self):
        rejected = [
            (), ("",), ("Movies",), ("AnimeArt",), ("anime",),
            ("anime,Movies",), ("Games, AnimeArt",), ("--worker",),
            ("Games,Anime,Music", "extra"),
        ]
        for tags in rejected:
            with self.subTest(tags=tags):
                self.assertIsNone(self.call(*tags))

        for tags in [
            "Anime", "Anime,Movies", "Movies, Anime, TV",
            "  Anime  ", "Games,\tAnime\t", ",Anime,",
        ]:
            with self.subTest(tags=tags):
                pending = self.call(tags)
                self.assertIsNotNone(pending)
                self.assertRegex(pending, r"^\d+ \d+\n$")

    def test_other_torrents_do_not_reset_pending_anime_scan(self):
        first = self.call("Movies, Anime")
        for tags in ("Movies", "AnimeArt", "", "anime,Movies"):
            self.assertEqual(self.call(tags), first)
        updated = self.call("TV,Anime")
        self.assertEqual(int(updated.split()[1]), int(first.split()[1]) + 1)
