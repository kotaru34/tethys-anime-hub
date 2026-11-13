"""Read-only inventory comparison tests (no Shoko API calls)."""
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from audit_inventory import normalize_relative, differences, disk_inventory


class InventoryTests(unittest.TestCase):
    def test_relative_path_normalization_and_safety(self):
        self.assertEqual(normalize_relative(r"Release\Episode 01.mkv"), "Release/Episode 01.mkv")
        self.assertEqual(normalize_relative("./Release/file.mkv"), "Release/file.mkv")
        self.assertIsNone(normalize_relative("../secret.mkv"))
        self.assertIsNone(normalize_relative("/Anime/secret.mkv"))
        self.assertIsNone(normalize_relative(""))

    def test_actual_missing_stale_and_size_changes(self):
        on_disk = {"A/01.mkv": 300, "B/02.mkv": 500, "C/03.mkv": 800}
        index = {"A/01.mkv": 300, "C/03.mkv": 700, "D/old.mkv": 100}
        missing, stale, mismatch = differences(on_disk, index)
        self.assertEqual(missing, {"B/02.mkv": 500})
        self.assertEqual(stale, {"D/old.mkv": 100})
        self.assertEqual(mismatch, {"C/03.mkv": (800, 700)})

    def test_media_only_scan_never_mutates_files(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "Show").mkdir()
            (root / "Show" / "01.mkv").write_bytes(b"abc")
            (root / "Show" / "01.ass").write_bytes(b"subtitles")
            (root / "Show" / "02.MP4").write_bytes(b"12345")
            files, errors = disk_inventory(root)
            self.assertEqual(files, {"Show/01.mkv": 3, "Show/02.MP4": 5})
            self.assertEqual(errors, [])
            self.assertEqual((root / "Show" / "01.mkv").read_bytes(), b"abc")


if __name__ == "__main__":
    unittest.main()
