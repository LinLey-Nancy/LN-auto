"""Manage a connected Maa controller and its optional task runtime."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from maa.controller import Win32Controller

from nzm_auto.diagnostics.workspace import DebugWorkspace
from nzm_auto.runtime.task_runtime import TaskRuntime, load_task_runtime
from nzm_auto.runtime.win32_controller import (
    ControllerConnectionError,
    connect_controller,
    create_controller,
    deactivate_controller,
)
from nzm_auto.windowing.discovery import WindowInfo


@dataclass(slots=True)
class AutomationSession:
    """A reusable, terminal-independent automation connection.

    GUI code can create this object in a worker thread, initialize the task
    runtime only when recognition is needed, and always release the controller
    through ``close``.
    """

    controller: Win32Controller
    config: dict[str, Any]
    project_root: Path
    workspace: DebugWorkspace
    window: WindowInfo | None = None
    controller_raw_size: tuple[int, int] | None = None
    controller_image_size: tuple[int, int] | None = None
    _runtime: TaskRuntime | None = field(default=None, init=False, repr=False)
    _closed: bool = field(default=False, init=False, repr=False)

    @classmethod
    def connect(
        cls,
        window: WindowInfo,
        config: dict[str, Any],
        project_root: Path,
        workspace: DebugWorkspace,
        *,
        mouse_input: str | None = None,
        keyboard_input: str | None = None,
        mouse_lock_follow: bool | None = None,
        direct_screen_input: bool | None = None,
    ) -> AutomationSession:
        """Create and connect a controller, cleaning it up on partial failure."""
        controller_config = dict(config["controller"])
        if mouse_input is not None:
            controller_config["mouse_input"] = mouse_input
        if keyboard_input is not None:
            controller_config["keyboard_input"] = keyboard_input
        if mouse_lock_follow is not None:
            controller_config["mouse_lock_follow"] = mouse_lock_follow
        if direct_screen_input is not None:
            controller_config["direct_screen_input"] = direct_screen_input

        controller = create_controller(window, controller_config)
        try:
            controller_raw_size, controller_image_size = connect_controller(
                controller,
                controller_config,
            )
        except BaseException as error:
            try:
                deactivate_controller(controller)
            except ControllerConnectionError as cleanup_error:
                error.add_note(f"Controller cleanup also failed: {cleanup_error}")
            raise

        session_config = dict(config)
        session_config["controller"] = controller_config
        return cls(
            controller=controller,
            config=session_config,
            project_root=project_root.resolve(),
            workspace=workspace,
            window=window,
            controller_raw_size=controller_raw_size,
            controller_image_size=controller_image_size,
        )

    @property
    def closed(self) -> bool:
        return self._closed

    @property
    def runtime(self) -> TaskRuntime | None:
        return self._runtime

    @property
    def resource_path(self) -> Path:
        path = Path(self.config["runtime"]["resource_path"])
        if not path.is_absolute():
            path = self.project_root / path
        return path.resolve()

    def initialize_runtime(self) -> TaskRuntime:
        """Load and cache the Maa resource and Tasker for recognition/actions."""
        if self._closed:
            raise ControllerConnectionError("Cannot initialize a closed automation session.")
        if self._runtime is None:
            self._runtime = load_task_runtime(
                self.controller,
                self.resource_path,
                self.workspace.logs / "maa",
            )
        return self._runtime

    def close(self) -> None:
        """Deactivate the controller. Calling close repeatedly is safe."""
        if self._closed:
            return
        deactivate_controller(self.controller)
        self._closed = True

    def __enter__(self) -> AutomationSession:
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> bool:
        try:
            self.close()
        except ControllerConnectionError as cleanup_error:
            if exc_value is None:
                raise
            exc_value.add_note(f"Controller cleanup also failed: {cleanup_error}")
        return False
