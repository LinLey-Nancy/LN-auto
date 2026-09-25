"""Cancellable sequential engine for workflow version 2."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
import threading

from window_auto.application.session import AutomationSession
from window_auto.config.loader import MAX_TIME_MS
from window_auto.workflow.actions import ActionResult, TemplateNotFoundError, execute_action
from window_auto.workflow.context import CancellationToken, ExecutionContext, WorkflowCancelled
from window_auto.workflow.events import WorkflowEvent, WorkflowEventType
from window_auto.workflow.model import (
    KeyPressStep,
    MouseClickStep,
    TemplateMatchStep,
    TextInputStep,
    WaitStep,
    WorkflowDefinition,
)


class WorkflowExecutionError(RuntimeError):
    """Raised when a v2 workflow stops on a failed step."""


class WorkflowStepTimeoutError(RuntimeError):
    """Raised when one step exceeds the workflow default timeout."""


@dataclass(frozen=True, slots=True)
class StepRunResult:
    step_id: str
    succeeded: bool
    output: object | None = None
    error: str | None = None


@dataclass(frozen=True, slots=True)
class WorkflowRunResult:
    workflow_name: str
    steps: tuple[StepRunResult, ...]
    cancelled: bool = False


EventCallback = Callable[[WorkflowEvent], None]


class WorkflowEngine:
    def __init__(self, event_callback: EventCallback | None = None) -> None:
        self._event_callback = event_callback

    def _emit(
        self,
        event_type: WorkflowEventType,
        definition: WorkflowDefinition,
        *,
        step=None,
        message: str = "",
        details: dict | None = None,
    ) -> None:
        if self._event_callback is None:
            return
        self._event_callback(
            WorkflowEvent(
                type=event_type,
                workflow_name=definition.name,
                step_id=step.id if step else None,
                step_name=step.name if step else None,
                message=message,
                details=details or {},
            )
        )

    def run(
        self,
        definition: WorkflowDefinition,
        session: AutomationSession,
        cancellation: CancellationToken | None = None,
    ) -> WorkflowRunResult:
        cancellation = cancellation or CancellationToken()
        context = ExecutionContext(session=session, cancellation=cancellation)
        results: list[StepRunResult] = []
        self._emit(WorkflowEventType.WORKFLOW_STARTED, definition)

        try:
            for step in definition.steps:
                cancellation.check()
                if not step.enabled:
                    self._emit(WorkflowEventType.STEP_SKIPPED, definition, step=step)
                    continue
                retry_count = 0
                while True:
                    self._emit(WorkflowEventType.STEP_STARTED, definition, step=step)
                    try:
                        action_result = self._execute_step(
                            step,
                            definition,
                            context,
                            cancellation,
                        )
                    except WorkflowCancelled:
                        raise
                    except Exception as error:
                        if (
                            step.on_failure == "retry"
                            and isinstance(error, TemplateNotFoundError)
                        ):
                            retry_count += 1
                            retry_delay_ms = int(getattr(step, "interval_ms", 0))
                            self._emit(
                                WorkflowEventType.STEP_FAILED,
                                definition,
                                step=step,
                                message=(
                                    f"{error} 将在 {retry_delay_ms} 毫秒后再次运行"
                                    f"（第 {retry_count} 次）。"
                                ),
                                details={"retry_count": retry_count},
                            )
                            cancellation.wait(retry_delay_ms / 1000.0)
                            continue
                        results.append(
                            StepRunResult(step_id=step.id, succeeded=False, error=str(error))
                        )
                        self._emit(
                            WorkflowEventType.STEP_FAILED,
                            definition,
                            step=step,
                            message=str(error),
                        )
                        should_stop = definition.settings.stop_on_error and (
                            step.on_failure in {"stop", "retry"}
                        )
                        if should_stop:
                            raise WorkflowExecutionError(
                                f"Step {step.name!r} failed: {error}"
                            ) from error
                        break
                    else:
                        results.append(
                            StepRunResult(
                                step_id=step.id,
                                succeeded=True,
                                output=action_result.output,
                            )
                        )
                        self._emit(
                            WorkflowEventType.STEP_SUCCEEDED,
                            definition,
                            step=step,
                            details={"output": action_result.output},
                        )
                        break
        except WorkflowCancelled:
            self._emit(WorkflowEventType.WORKFLOW_CANCELLED, definition)
            return WorkflowRunResult(definition.name, tuple(results), cancelled=True)
        except WorkflowExecutionError as error:
            self._emit(
                WorkflowEventType.WORKFLOW_FAILED,
                definition,
                message=str(error),
            )
            raise

        self._emit(WorkflowEventType.WORKFLOW_SUCCEEDED, definition)
        return WorkflowRunResult(definition.name, tuple(results))

    def _execute_step(
        self,
        step,
        definition: WorkflowDefinition,
        context: ExecutionContext,
        cancellation: CancellationToken,
    ) -> ActionResult:
        # A wait step is itself a deliberate delay, so its configured duration
        # is always allowed to complete; the timeout guards every other step.
        timeout_ms = definition.settings.default_timeout_ms
        if isinstance(step, WaitStep) or timeout_ms <= 0:
            return execute_action(step, context)

        # Steps that deliberately wait by configuration (recognition polling,
        # key holds, click/typing intervals) get that budget on top of the
        # default timeout, so a legal long-polling setup is never killed early.
        # The cap keeps threading.Timer far below platform overflow limits.
        timeout_ms = min(
            timeout_ms + _intrinsic_wait_budget_ms(step),
            7 * MAX_TIME_MS,
        )

        step_token = CancellationToken(parent=cancellation)
        watchdog = threading.Timer(timeout_ms / 1000.0, step_token.cancel)
        step_context = ExecutionContext(
            session=context.session,
            cancellation=step_token,
            variables=context.variables,
        )
        watchdog.start()
        try:
            return execute_action(step, step_context)
        except WorkflowCancelled:
            if cancellation.cancelled or not step_token.cancelled:
                raise
            raise WorkflowStepTimeoutError(
                f"Step exceeded the timeout of {timeout_ms} ms "
                f"(default {definition.settings.default_timeout_ms} ms plus the "
                "step's own configured waits); it was stopped at the next safe boundary."
            ) from None
        finally:
            watchdog.cancel()


def _intrinsic_wait_budget_ms(step) -> int:
    """Return the time one step deliberately spends waiting by configuration."""
    if isinstance(step, TemplateMatchStep):
        return step.attempts * step.interval_ms + step.post_action_interval_ms
    if isinstance(step, KeyPressStep):
        return step.hold_ms
    if isinstance(step, TextInputStep):
        if step.strategy == "key_sequence":
            return len(step.text) * step.interval_ms
        return 0
    if isinstance(step, MouseClickStep):
        return (step.count - 1) * step.interval_ms
    return 0


__all__ = ["CancellationToken", "WorkflowEngine", "WorkflowExecutionError"]
