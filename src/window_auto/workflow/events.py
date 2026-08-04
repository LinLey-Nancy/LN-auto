"""Structured workflow events suitable for Qt signals or CLI logging."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any


class WorkflowEventType(StrEnum):
    WORKFLOW_STARTED = "workflow_started"
    STEP_STARTED = "step_started"
    STEP_SUCCEEDED = "step_succeeded"
    STEP_FAILED = "step_failed"
    STEP_SKIPPED = "step_skipped"
    WORKFLOW_CANCELLED = "workflow_cancelled"
    WORKFLOW_FAILED = "workflow_failed"
    WORKFLOW_SUCCEEDED = "workflow_succeeded"


@dataclass(frozen=True, slots=True)
class WorkflowEvent:
    type: WorkflowEventType
    workflow_name: str
    step_id: str | None = None
    step_name: str | None = None
    message: str = ""
    details: dict[str, Any] = field(default_factory=dict)
    occurred_at: datetime = field(default_factory=datetime.now)
