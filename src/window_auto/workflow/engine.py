"""Cancellable sequential engine for workflow version 2."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
import random
import threading

from window_auto.application.session import AutomationSession
from window_auto.config.loader import MAX_TIME_MS
from window_auto.paths import project_root as fallback_project_root
from window_auto.runtime.humanize import humanize_from_config
from window_auto.workflow.actions import (
    ActionResult,
    TemplateNotFoundError,
    WorkflowActionError,
    execute_action,
)
from window_auto.workflow.context import CancellationToken, ExecutionContext, WorkflowCancelled
from window_auto.workflow.events import WorkflowEvent, WorkflowEventType
from window_auto.workflow.loader import WorkflowV2ConfigError, load_workflow_v2
from window_auto.workflow.model import (
    AutoDelay,
    KeyPressStep,
    MouseClickStep,
    OcrMatchStep,
    RunWorkflowStep,
    TemplateMatchStep,
    TextInputStep,
    WaitStep,
    WorkflowDefinition,
)


# SystemRandom draws from the OS entropy source, so random delays cannot be
# predicted or reproduced from a seeded pseudo-random sequence.
_AUTO_DELAY_RANDOM = random.SystemRandom()

# Sub-workflows (run_workflow steps) may nest, but only to a bounded depth so a
# misconfigured chain cannot recurse forever.
MAX_SUB_WORKFLOW_DEPTH = 8


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
        return self._run_definition(definition, context, cancellation)

    def _run_definition(
        self,
        definition: WorkflowDefinition,
        context: ExecutionContext,
        cancellation: CancellationToken,
    ) -> WorkflowRunResult:
        results: list[StepRunResult] = []
        self._emit(WorkflowEventType.WORKFLOW_STARTED, definition)

        try:
            for index, step in enumerate(definition.steps):
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
                                f"步骤“{step.name}”失败：{error}"
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
                self._apply_auto_delay(definition, cancellation, index, step)
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

    def _run_sub_workflow(
        self,
        step: RunWorkflowStep,
        context: ExecutionContext,
        cancellation: CancellationToken,
    ) -> ActionResult:
        path = step.workflow_path
        if path in context.workflow_stack:
            chain = " → ".join(p.name for p in (*context.workflow_stack, path))
            raise WorkflowActionError(f"检测到子工作流循环调用：{chain}。")
        if len(context.workflow_stack) >= MAX_SUB_WORKFLOW_DEPTH:
            raise WorkflowActionError(
                f"子工作流嵌套层级超过上限 {MAX_SUB_WORKFLOW_DEPTH} 层。"
            )
        session_root = getattr(context.session, "project_root", None)
        try:
            definition = load_workflow_v2(path, session_root or fallback_project_root())
        except WorkflowV2ConfigError as error:
            raise WorkflowActionError(f"子工作流无法加载：{error}") from error
        child_token = CancellationToken(parent=cancellation)
        child_context = ExecutionContext(
            session=context.session,
            cancellation=child_token,
            variables=context.variables,
            pointer=context.pointer,
            workflow_stack=(*context.workflow_stack, path),
        )
        result = self._run_definition(definition, child_context, child_token)
        context.pointer = child_context.pointer
        if result.cancelled:
            raise WorkflowCancelled("Workflow execution was cancelled.")
        failed = [item for item in result.steps if not item.succeeded]
        return ActionResult(
            f"子工作流“{definition.name}”完成："
            f"{len(result.steps) - len(failed)}/{len(result.steps)} 个步骤成功"
        )

    def _apply_auto_delay(
        self,
        definition: WorkflowDefinition,
        cancellation: CancellationToken,
        step_index: int,
        step,
    ) -> None:
        auto_delay: AutoDelay = definition.settings.auto_delay
        if step_index + 1 >= len(definition.steps) or auto_delay.mode == "none":
            return
        if auto_delay.mode == "fixed":
            delay_ms = auto_delay.fixed_ms
        else:
            delay_ms = _AUTO_DELAY_RANDOM.randint(auto_delay.min_ms, auto_delay.max_ms)
        if delay_ms <= 0:
            return
        self._emit(
            WorkflowEventType.AUTO_DELAY,
            definition,
            step=step,
            message=f"自动延迟 {delay_ms} 毫秒",
            details={"auto_delay_ms": delay_ms, "mode": auto_delay.mode},
        )
        cancellation.wait(delay_ms / 1000.0)

    def _execute_step(
        self,
        step,
        definition: WorkflowDefinition,
        context: ExecutionContext,
        cancellation: CancellationToken,
    ) -> ActionResult:
        # A run_workflow step expands into another whole workflow whose total
        # duration is unknowable, so — like a wait step — it is exempt from the
        # default timeout; the sub-workflow's own steps stay guarded by the
        # sub-workflow's settings.
        if isinstance(step, RunWorkflowStep):
            return self._run_sub_workflow(step, context, cancellation)

        # A wait step is itself a deliberate delay, so its configured duration
        # is always allowed to complete; the timeout guards every other step.
        timeout_ms = definition.settings.default_timeout_ms
        if isinstance(step, WaitStep) or timeout_ms <= 0:
            return execute_action(step, context)

        # Steps that deliberately wait by configuration (recognition polling,
        # key holds, click/typing intervals) get that budget on top of the
        # default timeout, so a legal long-polling setup is never killed early.
        # Timing jitter extends each wait by up to the configured ratio, and
        # the cap keeps threading.Timer far below platform overflow limits.
        humanize = humanize_from_config(getattr(context.session, "config", {}) or {})
        intrinsic_ms = _intrinsic_wait_budget_ms(step)
        if humanize.enabled and humanize.timing_jitter_ratio > 0:
            intrinsic_ms = int(intrinsic_ms * (1.0 + humanize.timing_jitter_ratio))
        timeout_ms = min(
            timeout_ms + intrinsic_ms,
            7 * MAX_TIME_MS,
        )

        step_token = CancellationToken(parent=cancellation)
        watchdog = threading.Timer(timeout_ms / 1000.0, step_token.cancel)
        step_context = ExecutionContext(
            session=context.session,
            cancellation=step_token,
            variables=context.variables,
            pointer=context.pointer,
        )
        watchdog.start()
        try:
            return execute_action(step, step_context)
        except WorkflowCancelled:
            if cancellation.cancelled or not step_token.cancelled:
                raise
            raise WorkflowStepTimeoutError(
                f"步骤执行超时：超过 {timeout_ms} 毫秒限制（默认 "
                f"{definition.settings.default_timeout_ms} 毫秒，"
                "另加步骤自身配置的等待时间），已在安全边界停止。"
                "可在工作流设置中调大 default_timeout_ms 后重试。"
            ) from None
        finally:
            context.pointer = step_context.pointer
            watchdog.cancel()


def _intrinsic_wait_budget_ms(step) -> int:
    """Return the time one step deliberately spends waiting by configuration."""
    if isinstance(step, (TemplateMatchStep, OcrMatchStep)):
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
