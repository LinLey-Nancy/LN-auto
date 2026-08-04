"""Mutable execution context and cooperative cancellation."""

from __future__ import annotations

from dataclasses import dataclass, field
from threading import Event
from typing import Any

from window_auto.application.session import AutomationSession


class WorkflowCancelled(RuntimeError):
    """Raised at safe boundaries after cancellation is requested."""


class CancellationToken:
    def __init__(self) -> None:
        self._event = Event()

    @property
    def cancelled(self) -> bool:
        return self._event.is_set()

    def cancel(self) -> None:
        self._event.set()

    def check(self) -> None:
        if self.cancelled:
            raise WorkflowCancelled("Workflow execution was cancelled.")

    def wait(self, seconds: float) -> None:
        if self._event.wait(max(0.0, seconds)):
            raise WorkflowCancelled("Workflow execution was cancelled.")


@dataclass(slots=True)
class ExecutionContext:
    session: AutomationSession
    cancellation: CancellationToken
    variables: dict[str, Any] = field(default_factory=dict)
