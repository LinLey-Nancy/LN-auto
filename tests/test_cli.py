import contextlib
import io
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from window_auto import cli


class _Job:
    def __init__(self, succeeded: bool) -> None:
        self.succeeded = succeeded

    def wait(self):
        return self


class _Controller:
    def __init__(self, click_succeeds: bool) -> None:
        self.click_succeeds = click_succeeds
        self.resolution = (1920, 1080)

    def post_click(self, x: int, y: int, contact: int = 0) -> _Job:
        return _Job(self.click_succeeds)


class _Session:
    def __init__(self, click_succeeds: bool) -> None:
        self.controller = _Controller(click_succeeds)
        self.config = {"controller": {}}

    def initialize_runtime(self):
        return object()

    def close(self) -> None:
        pass


class _FakeWindow:
    hwnd = 0x1234
    class_name = "FakeClass"
    title = "Fake Window"


class _Args:
    config = Path("config/default.json")
    title = None
    class_name = None
    visible_only = False
    index = 0
    input_profile = "foreground-precise"
    yes = True

    def __init__(self, workflow: Path) -> None:
        self.workflow = workflow


def _write_workflow(directory: Path) -> Path:
    path = directory / "workflow.json"
    path.write_text(
        json.dumps(
            {
                "version": 2,
                "name": "partial-failure",
                "settings": {"stop_on_error": False},
                "steps": [
                    {
                        "id": "click",
                        "type": "mouse_click",
                        "name": "click",
                        "x": 1,
                        "y": 1,
                        "on_failure": "continue",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    return path


class WorkflowV2CliTests(unittest.TestCase):
    def _run(self, click_succeeds: bool) -> tuple[int, str, str]:
        with TemporaryDirectory() as directory:
            workflow = _write_workflow(Path(directory))
            stdout, stderr = io.StringIO(), io.StringIO()
            with (
                patch.object(cli, "choose_window_for_run", return_value=_FakeWindow()),
                patch.object(
                    cli.AutomationSession,
                    "connect",
                    return_value=_Session(click_succeeds),
                ),
                contextlib.redirect_stdout(stdout),
                contextlib.redirect_stderr(stderr),
            ):
                exit_code = cli.run_workflow_v2_program(_Args(workflow))
        return exit_code, stdout.getvalue(), stderr.getvalue()

    def test_failed_step_is_reported_as_failure_with_nonzero_exit(self) -> None:
        exit_code, stdout, stderr = self._run(click_succeeds=False)

        self.assertEqual(exit_code, 11)
        self.assertNotIn("Workflow v2 succeeded", stdout)
        self.assertIn("failed", stderr)

    def test_successful_run_keeps_zero_exit(self) -> None:
        exit_code, stdout, _stderr = self._run(click_succeeds=True)

        self.assertEqual(exit_code, 0)
        self.assertIn("Workflow v2 succeeded", stdout)


class CliRobustnessTests(unittest.TestCase):
    def test_missing_config_is_a_clean_error_not_a_traceback(self) -> None:
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            exit_code = cli.main(["run", "--config", "does-not-exist.json", "--index", "0"])

        self.assertEqual(exit_code, 1)
        self.assertIn("Configuration failed", stderr.getvalue())

    def test_choose_json_keeps_stdout_machine_readable(self) -> None:
        window = type(
            "W",
            (),
            {
                "hwnd": 0x10, "title": "记事本", "class_name": "Notepad",
                "window_width": 800, "window_height": 600,
                "client_width": 800, "client_height": 600,
                "visible": True, "minimized": False,
                "to_dict": lambda self: {"hwnd": 0x10},
            },
        )()
        stdout, stderr = io.StringIO(), io.StringIO()
        with (
            patch.object(cli, "list_windows", return_value=[window]),
            patch("sys.stdin", io.StringIO("0\n")),
            contextlib.redirect_stdout(stdout),
            contextlib.redirect_stderr(stderr),
        ):
            exit_code = cli.run_window_choose(None, None, False, None, True)

        self.assertEqual(exit_code, 0)
        self.assertTrue(stdout.getvalue().lstrip().startswith("{"))
        self.assertIn("INDEX", stderr.getvalue())

    def test_choose_without_stdin_fails_cleanly(self) -> None:
        window = type(
            "W",
            (),
            {
                "hwnd": 0x10, "title": "A", "class_name": "C",
                "window_width": 1, "window_height": 1,
                "client_width": 1, "client_height": 1,
                "visible": True, "minimized": False,
            },
        )()
        with (
            patch.object(cli, "list_windows", return_value=[window]),
            patch("sys.stdin", None),
            contextlib.redirect_stderr(io.StringIO()),
        ):
            with self.assertRaises(cli.WindowSelectionError):
                cli.choose_window_for_run(None, None, False, None)


if __name__ == "__main__":
    unittest.main()
