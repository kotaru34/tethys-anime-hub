"""Regression for newline-less /proc/<pid>/wchan under set -e."""
from pathlib import Path
import subprocess
import tempfile
import unittest


class ProcfsWatchdogTest(unittest.TestCase):
    def test_no_trailing_newline_does_not_abort_shell(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "wchan"
            path.write_bytes(b"kernel_clone")  # Exact procfs encoding: no newline.
            failed = subprocess.run(
                ["bash", "-ec", 'read -r wchan < "$1"; test "$wchan" = kernel_clone', "bash", str(path)],
                capture_output=True,
            )
            self.assertNotEqual(failed.returncode, 0)
            passed = subprocess.run(
                ["bash", "-ec", 'wchan="$(cat "$1")"; test "$wchan" = kernel_clone', "bash", str(path)],
                capture_output=True,
            )
            self.assertEqual(passed.returncode, 0, passed.stderr)

    def test_production_watchdog_uses_newline_safe_read(self):
        script = (Path(__file__).resolve().parents[1] /
                  "torrenya-qbt-vfork-watchdog.sh").read_text()
        self.assertIn('wchan="$(cat "/proc/$main/task/$main/wchan"', script)
        self.assertNotIn('read -r wchan < "/proc/', script)
