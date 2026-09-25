import sys
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from window_auto.paths import project_root, workflow_dir


class WorkflowDirTests(unittest.TestCase):
    def test_source_checkout_uses_repo_root_workflow_directory(self) -> None:
        directory = workflow_dir()

        self.assertEqual(directory, project_root() / "workflow")
        self.assertTrue(directory.is_dir())

    def test_frozen_build_uses_sibling_of_executable(self) -> None:
        with TemporaryDirectory() as tmp:
            install_dir = Path(tmp) / "LN-auto"
            fake_exe = install_dir / "LN-auto.exe"
            fake_exe.parent.mkdir(parents=True)
            fake_exe.touch()
            with (
                patch.object(sys, "_MEIPASS", str(install_dir / "_internal"), create=True),
                patch.object(sys, "executable", str(fake_exe)),
            ):
                directory = workflow_dir()

            self.assertEqual(directory, (install_dir / "workflow").resolve())
            self.assertTrue(directory.is_dir())


if __name__ == "__main__":
    unittest.main()
