"""Background workflow execution bridge for Qt."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QObject, Signal, Slot

from window_auto.application.input_profiles import InputProfile
from window_auto.application.session import AutomationSession
from window_auto.diagnostics.workspace import DebugWorkspace
from window_auto.windowing.discovery import WindowInfo
from window_auto.workflow.context import CancellationToken
from window_auto.workflow.engine import WorkflowEngine
from window_auto.workflow.model import WorkflowDefinition


class WorkflowWorker(QObject):
    event_received = Signal(object)
    finished = Signal(bool, str)

    def __init__(
        self,
        definition: WorkflowDefinition,
        window: WindowInfo,
        config: dict,
        project_root: Path,
        workspace: DebugWorkspace,
        input_profile: InputProfile,
    ) -> None:
        super().__init__()
        self.definition = definition
        self.window = window
        self.config = config
        self.project_root = project_root
        self.workspace = workspace
        self.input_profile = input_profile
        self.cancellation = CancellationToken()

    def cancel(self) -> None:
        self.cancellation.cancel()

    @Slot()
    def run(self) -> None:
        session = None
        try:
            session = AutomationSession.connect(
                self.window,
                self.config,
                self.project_root,
                self.workspace,
                mouse_input=self.input_profile.mouse_method,
                keyboard_input=self.input_profile.keyboard_method,
                mouse_lock_follow=self.input_profile.mouse_lock_follow,
                direct_screen_input=self.input_profile.direct_screen_input,
            )
            result = WorkflowEngine(self.event_received.emit).run(
                self.definition,
                session,
                self.cancellation,
            )
            if result.cancelled:
                self.finished.emit(False, "工作流已停止。")
            else:
                self.finished.emit(True, f"工作流“{result.workflow_name}”执行完成。")
        except Exception as error:
            self.finished.emit(False, str(error))
        finally:
            if session is not None:
                try:
                    session.close()
                except Exception as error:
                    self.event_received.emit(
                        {
                            "type": "cleanup_failed",
                            "message": str(error),
                        }
                    )
