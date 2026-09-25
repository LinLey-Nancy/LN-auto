from pathlib import Path
import logging
import tempfile
import unittest

from window_auto.diagnostics.workspace import (
    _FILE_HANDLER_MARK,
    configure_file_logging,
    create_debug_workspace,
)


class DebugWorkspaceTests(unittest.TestCase):
    def test_workspace_directories_are_created(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = create_debug_workspace(Path(directory), "debug")

            self.assertTrue(workspace.logs.is_dir())
            self.assertTrue(workspace.screenshots.is_dir())
            self.assertTrue(workspace.reports.is_dir())
            self.assertFalse((workspace.root / "templates").exists())
            self.assertFalse((workspace.root / "temp").exists())

    def test_repeated_file_logging_replaces_the_previous_handler(self) -> None:
        root_logger = logging.getLogger()
        with tempfile.TemporaryDirectory() as directory:
            workspace = create_debug_workspace(Path(directory), "debug")
            first_path = configure_file_logging(workspace)
            second_path = configure_file_logging(workspace)

            marked = [
                handler
                for handler in root_logger.handlers
                if getattr(handler, _FILE_HANDLER_MARK, False)
            ]

            self.assertEqual(len(marked), 1)
            self.assertEqual(Path(marked[0].baseFilename), second_path)

            for handler in marked:
                root_logger.removeHandler(handler)
                handler.close()
