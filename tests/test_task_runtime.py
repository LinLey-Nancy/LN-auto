import json
from pathlib import Path
import unittest
from unittest.mock import patch

from window_auto.runtime.task_runtime import TaskRuntimeError, run_task


class _CompletedJob:
    def __init__(self, succeeded: bool = True) -> None:
        self.succeeded = succeeded
        self.done = True


class _PendingJob:
    succeeded = False
    done = False


class _FakeTasker:
    def __init__(self, task_job) -> None:
        self.task_job = task_job
        self.stop_job = _CompletedJob()
        self.stop_calls = 0

    def post_task(self, entry: str):
        return self.task_job

    def post_stop(self):
        self.stop_calls += 1
        return self.stop_job


class FrameworkPipelineTests(unittest.TestCase):
    def test_self_test_pipeline_has_no_input_action(self) -> None:
        project_root = Path(__file__).resolve().parents[1]
        pipeline_path = project_root / "assets" / "resource" / "pipeline" / "framework.json"
        with pipeline_path.open(encoding="utf-8") as file:
            pipeline = json.load(file)

        node = pipeline["FrameworkSelfTest"]
        self.assertEqual(node["recognition"], "DirectHit")
        self.assertEqual(node["action"], "DoNothing")

    def test_completed_task_succeeds_before_timeout(self) -> None:
        tasker = _FakeTasker(_CompletedJob())
        runtime = type("Runtime", (), {"tasker": tasker})()

        run_task(runtime, "FrameworkSelfTest", 1)

        self.assertEqual(tasker.stop_calls, 0)

    def test_timed_out_task_requests_stop(self) -> None:
        tasker = _FakeTasker(_PendingJob())
        runtime = type("Runtime", (), {"tasker": tasker})()

        with (
            patch(
                "window_auto.runtime.task_runtime.time.monotonic",
                side_effect=[0.0, 2.0, 2.0],
            ),
            self.assertRaisesRegex(TaskRuntimeError, "timed out after 1 seconds"),
        ):
            run_task(runtime, "StuckTask", 1)

        self.assertEqual(tasker.stop_calls, 1)
