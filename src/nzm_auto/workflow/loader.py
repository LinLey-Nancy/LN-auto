"""Strict JSON loader for workflow version 2."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from nzm_auto.workflow.model import (
    KeyPressStep,
    MouseClickStep,
    MouseMoveStep,
    TemplateMatchStep,
    TextInputStep,
    WaitStep,
    WindowTarget,
    WorkflowDefinition,
    WorkflowSettings,
    WorkflowStep,
)


class WorkflowV2ConfigError(RuntimeError):
    """Raised when a version 2 workflow is invalid."""


_ROOT_FIELDS = {"version", "name", "target", "settings", "steps"}
_BASE_FIELDS = {"id", "type", "name", "enabled", "on_failure"}
_TYPE_FIELDS = {
    "wait": {
        "delay_mode",
        "duration_ms",
        "min_duration_ms",
        "max_duration_ms",
    },
    "mouse_move": {"move_mode", "x", "y", "delta_x", "delta_y"},
    "mouse_click": {"x", "y", "match_variable", "button", "count", "interval_ms"},
    "key_press": {"key", "modifiers", "hold_ms"},
    "text_input": {"text", "strategy", "interval_ms", "sensitive"},
    "template_match": {
        "template",
        "threshold",
        "attempts",
        "interval_ms",
        "result_variable",
        "post_action",
        "post_button",
        "post_action_interval_ms",
        "post_key",
        "post_modifiers",
        "post_key_hold_ms",
    },
}


def _object(value: Any, context: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise WorkflowV2ConfigError(f"{context} must be a JSON object.")
    return value


def _reject_unknown(data: dict[str, Any], allowed: set[str], context: str) -> None:
    unknown = sorted(set(data) - allowed)
    if unknown:
        raise WorkflowV2ConfigError(f"Unknown {context} field(s): {', '.join(unknown)}.")


def _string(data: dict[str, Any], field: str, context: str) -> str:
    value = data.get(field)
    if not isinstance(value, str) or not value.strip():
        raise WorkflowV2ConfigError(f"{context}.{field} must be a non-empty string.")
    return value.strip()


def _integer(
    data: dict[str, Any],
    field: str,
    context: str,
    *,
    default: int | None = None,
    minimum: int = 0,
    maximum: int | None = None,
) -> int:
    value = data.get(field, default)
    if isinstance(value, bool) or not isinstance(value, int):
        raise WorkflowV2ConfigError(f"{context}.{field} must be an integer.")
    if value < minimum or maximum is not None and value > maximum:
        limit = f" from {minimum} to {maximum}" if maximum is not None else f" at least {minimum}"
        raise WorkflowV2ConfigError(f"{context}.{field} must be{limit}.")
    return value


def _key_value(
    data: dict[str, Any],
    field: str,
    context: str,
    *,
    default: str | int | None = None,
) -> str | int:
    value = data.get(field, default)
    if isinstance(value, bool) or not isinstance(value, (str, int)) or value == "":
        raise WorkflowV2ConfigError(
            f"{context}.{field} must be a key name or virtual key code."
        )
    return value


def _modifiers(
    data: dict[str, Any],
    field: str,
    context: str,
) -> tuple[str | int, ...]:
    values = data.get(field, [])
    if not isinstance(values, list) or any(
        isinstance(value, bool) or not isinstance(value, (str, int))
        for value in values
    ):
        raise WorkflowV2ConfigError(
            f"{context}.{field} must be an array of key names/codes."
        )
    return tuple(values)


def _base(
    data: dict[str, Any],
    context: str,
    *,
    allow_retry: bool = False,
) -> dict[str, Any]:
    enabled = data.get("enabled", True)
    if not isinstance(enabled, bool):
        raise WorkflowV2ConfigError(f"{context}.enabled must be a boolean.")
    on_failure = data.get("on_failure", "stop")
    allowed_failure_policies = {"stop", "continue"}
    if allow_retry:
        allowed_failure_policies.add("retry")
    if on_failure not in allowed_failure_policies:
        choices = "'stop', 'continue', or 'retry'" if allow_retry else "'stop' or 'continue'"
        raise WorkflowV2ConfigError(f"{context}.on_failure must be {choices}.")
    return {
        "id": _string(data, "id", context),
        "name": _string(data, "name", context),
        "enabled": enabled,
        "on_failure": on_failure,
    }


def _load_step(data: dict[str, Any], context: str, project_root: Path) -> WorkflowStep:
    step_type = _string(data, "type", context)
    if step_type not in _TYPE_FIELDS:
        raise WorkflowV2ConfigError(f"{context}.type is unsupported: {step_type!r}.")
    _reject_unknown(data, _BASE_FIELDS | _TYPE_FIELDS[step_type], context)
    base = _base(data, context, allow_retry=step_type == "template_match")

    if step_type == "wait":
        delay_mode = data.get("delay_mode", "fixed")
        if delay_mode not in {"fixed", "random"}:
            raise WorkflowV2ConfigError(
                f"{context}.delay_mode must be 'fixed' or 'random'."
            )
        duration_ms = _integer(data, "duration_ms", context, default=0, minimum=0)
        min_duration_ms = _integer(
            data,
            "min_duration_ms",
            context,
            default=duration_ms,
            minimum=0,
        )
        max_duration_ms = _integer(
            data,
            "max_duration_ms",
            context,
            default=duration_ms,
            minimum=0,
        )
        if min_duration_ms > max_duration_ms:
            raise WorkflowV2ConfigError(
                f"{context}.min_duration_ms must not exceed max_duration_ms."
            )
        return WaitStep(
            **base,
            delay_mode=delay_mode,
            duration_ms=duration_ms,
            min_duration_ms=min_duration_ms,
            max_duration_ms=max_duration_ms,
        )
    if step_type == "mouse_move":
        move_mode = data.get("move_mode", "absolute")
        if move_mode not in {"absolute", "relative"}:
            raise WorkflowV2ConfigError(
                f"{context}.move_mode must be 'absolute' or 'relative'."
            )
        return MouseMoveStep(
            **base,
            move_mode=move_mode,
            x=_integer(data, "x", context, default=0, minimum=0),
            y=_integer(data, "y", context, default=0, minimum=0),
            delta_x=_integer(
                data,
                "delta_x",
                context,
                default=0,
                minimum=-1_000_000,
                maximum=1_000_000,
            ),
            delta_y=_integer(
                data,
                "delta_y",
                context,
                default=0,
                minimum=-1_000_000,
                maximum=1_000_000,
            ),
        )
    if step_type == "mouse_click":
        x = data.get("x")
        y = data.get("y")
        match_variable = data.get("match_variable")
        uses_point = x is not None or y is not None
        uses_match = match_variable is not None
        if uses_point == uses_match or uses_point and (x is None or y is None):
            raise WorkflowV2ConfigError(
                f"{context} must define either both x/y or match_variable."
            )
        if uses_point:
            x = _integer(data, "x", context, minimum=0)
            y = _integer(data, "y", context, minimum=0)
        else:
            match_variable = _string(data, "match_variable", context)
        button = data.get("button", "left")
        if button not in {"left", "right", "middle"}:
            raise WorkflowV2ConfigError(
                f"{context}.button must be 'left', 'right', or 'middle'."
            )
        return MouseClickStep(
            **base,
            x=x,
            y=y,
            match_variable=match_variable,
            button=button,
            count=_integer(data, "count", context, default=1, minimum=1, maximum=2),
            interval_ms=_integer(data, "interval_ms", context, default=100, minimum=0),
        )
    if step_type == "key_press":
        return KeyPressStep(
            **base,
            key=_key_value(data, "key", context),
            modifiers=_modifiers(data, "modifiers", context),
            hold_ms=_integer(data, "hold_ms", context, default=50, minimum=0),
        )
    if step_type == "text_input":
        text = data.get("text")
        if not isinstance(text, str):
            raise WorkflowV2ConfigError(f"{context}.text must be a string.")
        strategy = data.get("strategy", "key_sequence")
        if strategy not in {"key_sequence", "direct"}:
            raise WorkflowV2ConfigError(
                f"{context}.strategy must be 'key_sequence' or 'direct'."
            )
        sensitive = data.get("sensitive", False)
        if not isinstance(sensitive, bool):
            raise WorkflowV2ConfigError(f"{context}.sensitive must be a boolean.")
        return TextInputStep(
            **base,
            text=text,
            strategy=strategy,
            interval_ms=_integer(
                data,
                "interval_ms",
                context,
                default=80,
                minimum=0,
            ),
            sensitive=sensitive,
        )

    template = Path(_string(data, "template", context))
    if not template.is_absolute():
        template = project_root / template
    template = template.resolve()
    if not template.is_file():
        raise WorkflowV2ConfigError(f"{context}.template does not exist: {template}")
    threshold = data.get("threshold", 0.8)
    if isinstance(threshold, bool) or not isinstance(threshold, (int, float)):
        raise WorkflowV2ConfigError(f"{context}.threshold must be a number.")
    threshold = float(threshold)
    if not 0.0 < threshold <= 1.0:
        raise WorkflowV2ConfigError(f"{context}.threshold must be greater than 0 and at most 1.")
    post_action = data.get("post_action", "none")
    if post_action not in {"none", "click", "double_click", "key_press"}:
        raise WorkflowV2ConfigError(
            f"{context}.post_action must be 'none', 'click', 'double_click', or 'key_press'."
        )
    post_button = data.get("post_button", "left")
    if post_button not in {"left", "right", "middle"}:
        raise WorkflowV2ConfigError(
            f"{context}.post_button must be 'left', 'right', or 'middle'."
        )
    return TemplateMatchStep(
        **base,
        template_path=template,
        threshold=threshold,
        attempts=_integer(data, "attempts", context, default=1, minimum=1, maximum=100),
        interval_ms=_integer(data, "interval_ms", context, default=500, minimum=0),
        result_variable=_string(data, "result_variable", context),
        post_action=post_action,
        post_button=post_button,
        post_action_interval_ms=_integer(
            data,
            "post_action_interval_ms",
            context,
            default=100,
            minimum=0,
        ),
        post_key=_key_value(data, "post_key", context, default="ENTER"),
        post_modifiers=_modifiers(data, "post_modifiers", context),
        post_key_hold_ms=_integer(
            data,
            "post_key_hold_ms",
            context,
            default=50,
            minimum=0,
        ),
    )


def load_workflow_v2(path: Path, project_root: Path) -> WorkflowDefinition:
    try:
        raw = json.loads(path.read_text(encoding="utf-8-sig"))
    except OSError as error:
        raise WorkflowV2ConfigError(f"Failed to read workflow {path}: {error}") from error
    except json.JSONDecodeError as error:
        raise WorkflowV2ConfigError(f"Invalid workflow JSON {path}: {error}") from error

    root = _object(raw, "workflow")
    _reject_unknown(root, _ROOT_FIELDS, "workflow")
    if root.get("version") != 2:
        raise WorkflowV2ConfigError("workflow.version must be 2.")

    target = None
    if "target" in root:
        raw_target = _object(root["target"], "workflow.target")
        _reject_unknown(raw_target, {"title_pattern", "class_name"}, "workflow.target")
        title_pattern = raw_target.get("title_pattern", "")
        if not isinstance(title_pattern, str):
            raise WorkflowV2ConfigError(
                "workflow.target.title_pattern must be a string."
            )
        title_pattern = title_pattern.strip()
        class_name = raw_target.get("class_name")
        if class_name is not None and not isinstance(class_name, str):
            raise WorkflowV2ConfigError("workflow.target.class_name must be a string or null.")
        class_name = class_name.strip() if class_name else None
        if title_pattern or class_name:
            target = WindowTarget(
                title_pattern=title_pattern,
                class_name=class_name,
            )

    settings = WorkflowSettings()
    if "settings" in root:
        raw_settings = _object(root["settings"], "workflow.settings")
        _reject_unknown(
            raw_settings,
            {"stop_on_error", "default_timeout_ms"},
            "workflow.settings",
        )
        stop_on_error = raw_settings.get("stop_on_error", True)
        if not isinstance(stop_on_error, bool):
            raise WorkflowV2ConfigError("workflow.settings.stop_on_error must be a boolean.")
        settings = WorkflowSettings(
            stop_on_error=stop_on_error,
            default_timeout_ms=_integer(
                raw_settings,
                "default_timeout_ms",
                "workflow.settings",
                default=10_000,
                minimum=1,
            ),
        )

    raw_steps = root.get("steps")
    if not isinstance(raw_steps, list) or not raw_steps:
        raise WorkflowV2ConfigError("workflow.steps must be a non-empty array.")
    steps: list[WorkflowStep] = []
    ids: set[str] = set()
    for index, raw_step in enumerate(raw_steps):
        context = f"workflow.steps[{index}]"
        step = _load_step(_object(raw_step, context), context, project_root)
        if step.id in ids:
            raise WorkflowV2ConfigError(f"Duplicate workflow step id: {step.id!r}.")
        ids.add(step.id)
        steps.append(step)

    return WorkflowDefinition(
        name=_string(root, "name", "workflow"),
        steps=tuple(steps),
        target=target,
        settings=settings,
    )
