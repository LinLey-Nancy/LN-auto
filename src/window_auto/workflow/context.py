"""Mutable execution context and cooperative cancellation."""

from __future__ import annotations

from dataclasses import dataclass, field
from threading import Event
import time
from typing import Any

from window_auto.application.session import AutomationSession


class WorkflowCancelled(RuntimeError):
    """Raised at safe boundaries after cancellation is requested."""


class CancellationToken:
    """Cooperative cancellation token with optional parent propagation."""

    _PARENT_POLL_SECONDS = 0.05

    def __init__(self, parent: CancellationToken | None = None) -> None:
        self._event = Event()
        self._parent = parent

    @property
    def cancelled(self) -> bool:
        return self._event.is_set() or (
            self._parent is not None and self._parent.cancelled
        )

    def cancel(self) -> None:
        self._event.set()

    def check(self) -> None:
        if self.cancelled:
            raise WorkflowCancelled("Workflow execution was cancelled.")

    def wait(self, seconds: float) -> None:
        deadline = time.monotonic() + max(0.0, seconds)
        while True:
            self.check()
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return
            self._event.wait(min(remaining, self._PARENT_POLL_SECONDS))


@dataclass(slots=True)
class ExecutionContext:
    session: AutomationSession
    cancellation: CancellationToken
    variables: dict[str, Any] = field(default_factory=dict)
