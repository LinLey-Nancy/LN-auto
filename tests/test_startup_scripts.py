from __future__ import annotations

import os
from pathlib import Path
import subprocess
from tempfile import TemporaryDirectory
import unittest


PROJECT_ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(os.name == "nt", "Windows startup scripts are Windows-only")
class StartupScriptTests(unittest.TestCase):
    def test_elevated_command_uses_environment_marker_and_preserves_arguments(self) -> None:
        with TemporaryDirectory() as directory:
            temp_root = Path(directory)
            start_vbs = temp_root / "start.vbs"
            start_vbs.write_bytes((PROJECT_ROOT / "start.vbs").read_bytes())
            probe_path = temp_root / "probe.txt"
            (temp_root / "start.bat").write_text(
                "@echo off\n"
                f'> "{probe_path}" echo hidden=[%WINDOW_AUTO_HIDDEN%]\n'
                f'>> "{probe_path}" echo args=[%*]\n',
                encoding="ascii",
            )

            validation = subprocess.run(
                ["cscript.exe", "//nologo", str(start_vbs), "--validate-only"],
                check=True,
                capture_output=True,
                text=True,
            )
            command_arguments = validation.stdout.strip()

            self.assertIn("set WINDOW_AUTO_HIDDEN=1&& call ", command_arguments)
            self.assertNotIn("--elevated-hidden", command_arguments)
            subprocess.run(
                f'{os.environ["ComSpec"]} {command_arguments}',
                cwd=temp_root,
                check=True,
            )
            probe = probe_path.read_text(encoding="ascii").splitlines()
            self.assertEqual(probe, ["hidden=[1]", 'args=["--validate-only"]'])


if __name__ == "__main__":
    unittest.main()
