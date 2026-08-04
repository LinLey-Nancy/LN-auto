"""Load a Maa resource bundle and run the minimal framework task."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import time

from maa.controller import Win32Controller
from maa.job import Job
from maa.resource import Resource
from maa.tasker import Tasker


class TaskRuntimeError(RuntimeError):
    """Raised when Maa resources or tasks fail."""


@dataclass(slots=True)
class TaskRuntime:
    resource: Resource
    tasker: Tasker


def load_task_runtime(
    controller: Win32Controller,
    resource_path: Path,
    maa_log_dir: Path,
) -> TaskRuntime:
    maa_log_dir.mkdir(parents=True, exist_ok=True)
    if not Tasker.set_log_dir(maa_log_dir):
        raise TaskRuntimeError(f"Failed to set MaaFramework log directory: {maa_log_dir}")

    resource = Resource()
    load_job = resource.post_bundle(resource_path).wait()
    if not load_job.succeeded or not resource.loaded:
        raise TaskRuntimeError(f"Failed to load Maa resource bundle: {resource_path}")

    tasker = Tasker()
    if not tasker.bind(resource, controller) or not tasker.inited:
        raise TaskRuntimeError("Failed to bind Maa resource and controller to Tasker.")
    return TaskRuntime(resource=resource, tasker=tasker)


def wait_for_job(
    job: Job,
    timeout_seconds: float,
    poll_interval_seconds: float = 0.05,
) -> bool:
    """Wait up to the configured deadline without blocking in Maa's unbounded wait."""
    deadline = time.monotonic() + timeout_seconds
    while not job.done:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return False
        time.sleep(min(poll_interval_seconds, remaining))
    return True


def run_task(runtime: TaskRuntime, entry: str, timeout_seconds: float) -> None:
    task_job = runtime.tasker.post_task(entry)
    if not wait_for_job(task_job, timeout_seconds):
        stop_job = runtime.tasker.post_stop()
        stop_completed = wait_for_job(stop_job, min(timeout_seconds, 5.0))
        stop_status = (
            "stop request succeeded"
            if stop_completed and stop_job.succeeded
            else "stop request did not complete successfully"
        )
        raise TaskRuntimeError(
            f"Maa task timed out after {timeout_seconds:g} seconds: {entry}; {stop_status}."
        )
    if not task_job.succeeded:
        raise TaskRuntimeError(f"Maa task failed: {entry}")
