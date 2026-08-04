from pathlib import Path
import tempfile
import unittest

from window_auto.diagnostics.workspace import create_debug_workspace


class DebugWorkspaceTests(unittest.TestCase):
    def test_workspace_directories_are_created(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = create_debug_workspace(Path(directory), "debug")

            self.assertTrue(workspace.logs.is_dir())
            self.assertTrue(workspace.screenshots.is_dir())
            self.assertTrue(workspace.reports.is_dir())
            self.assertFalse((workspace.root / "templates").exists())
            self.assertFalse((workspace.root / "temp").exists())
