"""Load and execute a configuration-driven sequence of template actions."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import json
from pathlib import Path
import re
import time

from maa.controller import Win32Controller

from window_auto.config.loader import MAX_TIME_MS
from window_auto.automation.template_action import (
    TemplateActionResult,
    TemplateNotFoundError,
    load_template_image,
    run_template_action,
)
from window_auto.diagnostics.workspace import DebugWorkspace
from window_auto.runtime.task_runtime import TaskRuntime


class WorkflowConfigError(RuntimeError):
    """Raised when a workflow JSON file is invalid."""


class WorkflowExecutionError(RuntimeError):
    """Raised when a workflow cannot safely complete."""


@dataclass(frozen=True, slots=True)
class WorkflowStep:
    name: str
    template_path: Path
    threshold: float
    action: str
    recognition_attempts: int
    recognition_interval_seconds: float
    pre_delay_seconds: float
    post_delay_seconds: float
    require_visual_change: bool


@dataclass(frozen=True, slots=True)
class WorkflowDefinition:
    name: str
    steps: tuple[WorkflowStep, ...]


@dataclass(frozen=True, slots=True)
class WorkflowStepResult:
    name: str
    recognition_attempt: int
    action_result: TemplateActionResult


@dataclass(frozen=True, slots=True)
class WorkflowResult:
    name: str
    steps: tuple[WorkflowStepResult, ...]
    report_path: Path


_WORKFLOW_FIELDS = {"version", "name", "steps"}
_STEP_FIELDS = {
    "name",
    "template",
    "threshold",
    "action",
    "recognition_attempts",
    "recognition_interval_ms",
    "pre_delay_ms",
    "post_delay_ms",
    "require_visual_change",
}


def _reject_unknown_fields(data: dict, allowed: set[str], context: str) -> None:
    unknown = sorted(set(data) - allowed)
    if unknown:
        raise WorkflowConfigError(f"Unknown {context} field(s): {', '.join(unknown)}.")


def _required_string(data: dict, field: str, context: str) -> str:
    value = data.get(field)
    if not isinstance(value, str) or not value.strip():
        raise WorkflowConfigError(f"{context}.{field} must be a non-empty string.")
    return value.strip()


def _milliseconds(data: dict, field: str, default: int, context: str) -> float:
    value = data.get(field, default)
    if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= MAX_TIME_MS:
        raise WorkflowConfigError(
            f"{context}.{field} must be an integer from 0 to {MAX_TIME_MS}."
        )
    return value / 1000.0


def load_workflow(path: Path, project_root: Path) -> WorkflowDefinition:
    try:
        raw = json.loads(path.read_text(encoding="utf-8-sig"))
    except OSError as error:
        raise WorkflowConfigError(f"Failed to read workflow {path}: {error}") from error
    except json.JSONDecodeError as error:
        raise WorkflowConfigError(f"Invalid workflow JSON {path}: {error}") from error

    if not isinstance(raw, dict):
        raise WorkflowConfigError("Workflow root must be a JSON object.")
    _reject_unknown_fields(raw, _WORKFLOW_FIELDS, "workflow")
    if raw.get("version") != 1:
        raise WorkflowConfigError("workflow.version must be 1.")
    workflow_name = _required_string(raw, "name", "workflow")
    raw_steps = raw.get("steps")
    if not isinstance(raw_steps, list) or not raw_steps:
        raise WorkflowConfigError("workflow.steps must be a non-empty array.")

    steps: list[WorkflowStep] = []
    names: set[str] = set()
    for index, raw_step in enumerate(raw_steps):
        context = f"workflow.steps[{index}]"
        if not isinstance(raw_step, dict):
            raise WorkflowConfigError(f"{context} must be a JSON object.")
        _reject_unknown_fields(raw_step, _STEP_FIELDS, context)
        name = _required_string(raw_step, "name", context)
        if name in names:
            raise WorkflowConfigError(f"Duplicate workflow step name: {name!r}.")
        names.add(name)

        template_value = _required_string(raw_step, "template", context)
        template_path = Path(template_value)
        if not template_path.is_absolute():
            template_path = project_root / template_path
        template_path = template_path.resolve()
        if not template_path.is_file():
            raise WorkflowConfigError(f"{context}.template does not exist: {template_path}")

        threshold = raw_step.get("threshold", 0.8)
        if isinstance(threshold, bool) or not isinstance(threshold, (int, float)):
            raise WorkflowConfigError(f"{context}.threshold must be a number.")
        threshold = float(threshold)
        if not 0.0 < threshold <= 1.0:
            raise WorkflowConfigError(f"{context}.threshold must be greater than 0 and at most 1.")

        action = _required_string(raw_step, "action", context)
        if action not in {"click", "double-click"}:
            raise WorkflowConfigError(f"{context}.action must be 'click' or 'double-click'.")

        attempts = raw_step.get("recognition_attempts", 1)
        if isinstance(attempts, bool) or not isinstance(attempts, int) or not 1 <= attempts <= 100:
            raise WorkflowConfigError(
                f"{context}.recognition_attempts must be an integer from 1 to 100."
            )

        require_visual_change = raw_step.get("require_visual_change", True)
        if not isinstance(require_visual_change, bool):
            raise WorkflowConfigError(f"{context}.require_visual_change must be a boolean.")

        steps.append(
            WorkflowStep(
                name=name,
                template_path=template_path,
                threshold=threshold,
                action=action,
                recognition_attempts=attempts,
                recognition_interval_seconds=_milliseconds(
                    raw_step, "recognition_interval_ms", 500, context
                ),
                pre_delay_seconds=_milliseconds(raw_step, "pre_delay_ms", 0, context),
                post_delay_seconds=_milliseconds(raw_step, "post_delay_ms", 500, context),
                require_visual_change=require_visual_change,
            )
        )

    return WorkflowDefinition(workflow_name, tuple(steps))


def _safe_prefix(value: str) -> str:
    normalized = re.sub(r"[^A-Za-z0-9_-]+", "-", value).strip("-")
    return normalized or "step"


def run_workflow(
    definition: WorkflowDefinition,
    runtime: TaskRuntime,
    controller: Win32Controller,
    workspace: DebugWorkspace,
) -> WorkflowResult:
    step_results: list[WorkflowStepResult] = []
    for step_index, step in enumerate(definition.steps, start=1):
        template = load_template_image(step.template_path)
        if step.pre_delay_seconds:
            time.sleep(step.pre_delay_seconds)

        result = None
        for attempt in range(1, step.recognition_attempts + 1):
            prefix = f"workflow-{step_index:02d}-{_safe_prefix(step.name)}"
            try:
                result = run_template_action(
                    runtime,
                    controller,
                    template,
                    step.threshold,
                    step.action,
                    workspace.timestamped_path(workspace.screenshots, f"{prefix}-before", ".png"),
                    workspace.timestamped_path(workspace.screenshots, f"{prefix}-after", ".png"),
                    workspace.timestamped_path(workspace.screenshots, f"{prefix}-target", ".png"),
                    workspace.timestamped_path(
                        workspace.screenshots, f"{prefix}-difference", ".png"
                    ),
                    workspace.timestamped_path(workspace.reports, prefix, ".json"),
                    settle_seconds=step.post_delay_seconds,
                )
                break
            except TemplateNotFoundError as error:
                if attempt == step.recognition_attempts:
                    raise WorkflowExecutionError(
                        f"步骤“{step.name}”识别 {attempt} 次后仍未找到模板，"
                        "本步骤未发送输入。请确认目标画面已显示，或重新截取模板。"
                    ) from error
                time.sleep(step.recognition_interval_seconds)

        if result is None:
            raise WorkflowExecutionError(f"步骤“{step.name}”没有产生任何结果。")
        if step.require_visual_change and not result.difference.visual_change_detected:
            raise WorkflowExecutionError(
                f"步骤“{step.name}”已发送输入，但未检测到画面变化，"
                "工作流已停止且不再重试。请确认输入已生效，或关闭该步骤的画面变化验证。"
            )
        step_results.append(WorkflowStepResult(step.name, attempt, result))

    report_path = workspace.timestamped_path(workspace.reports, "workflow", ".json")
    report = {
        "name": definition.name,
        "steps": [
            {
                "name": step_result.name,
                "recognition_attempt": step_result.recognition_attempt,
                "action": step_result.action_result.action,
                "point": list(step_result.action_result.point),
                "score": step_result.action_result.score,
                "box": asdict(step_result.action_result.box),
                "difference": asdict(step_result.action_result.difference),
                "step_report_path": str(step_result.action_result.report_path),
            }
            for step_result in step_results
        ],
    }
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return WorkflowResult(definition.name, tuple(step_results), report_path.resolve())
