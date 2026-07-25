"""Typed, GUI-friendly workflow version 2 data model."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal, TypeAlias


FailurePolicy: TypeAlias = Literal["stop", "continue", "retry"]


@dataclass(frozen=True, slots=True)
class WindowTarget:
    title_pattern: str
    class_name: str | None = None


@dataclass(frozen=True, slots=True)
class WorkflowSettings:
    stop_on_error: bool = True
    default_timeout_ms: int = 10_000


@dataclass(frozen=True, slots=True)
class StepBase:
    id: str
    name: str
    enabled: bool = True
    on_failure: FailurePolicy = "stop"


@dataclass(frozen=True, slots=True)
class WaitStep(StepBase):
    delay_mode: Literal["fixed", "random"] = "fixed"
    duration_ms: int = 0
    min_duration_ms: int = 0
    max_duration_ms: int = 0
    kind: Literal["wait"] = field(default="wait", init=False)


@dataclass(frozen=True, slots=True)
class MouseMoveStep(StepBase):
    move_mode: Literal["absolute", "relative"] = "absolute"
    x: int = 0
    y: int = 0
    delta_x: int = 0
    delta_y: int = 0
    kind: Literal["mouse_move"] = field(default="mouse_move", init=False)


@dataclass(frozen=True, slots=True)
class MouseClickStep(StepBase):
    x: int | None = None
    y: int | None = None
    match_variable: str | None = None
    button: Literal["left", "right", "middle"] = "left"
    count: int = 1
    interval_ms: int = 100
    kind: Literal["mouse_click"] = field(default="mouse_click", init=False)


@dataclass(frozen=True, slots=True)
class KeyPressStep(StepBase):
    key: str | int = ""
    modifiers: tuple[str | int, ...] = ()
    hold_ms: int = 50
    kind: Literal["key_press"] = field(default="key_press", init=False)


@dataclass(frozen=True, slots=True)
class TextInputStep(StepBase):
    text: str = ""
    strategy: Literal["key_sequence", "direct"] = "key_sequence"
    interval_ms: int = 80
    sensitive: bool = False
    kind: Literal["text_input"] = field(default="text_input", init=False)


@dataclass(frozen=True, slots=True)
class TemplateMatchStep(StepBase):
    template_path: Path = Path()
    threshold: float = 0.8
    attempts: int = 1
    interval_ms: int = 500
    result_variable: str = ""
    post_action: Literal["none", "click", "double_click", "key_press"] = "none"
    post_button: Literal["left", "right", "middle"] = "left"
    post_action_interval_ms: int = 100
    post_key: str | int = "ENTER"
    post_modifiers: tuple[str | int, ...] = ()
    post_key_hold_ms: int = 50
    kind: Literal["template_match"] = field(default="template_match", init=False)


WorkflowStep: TypeAlias = (
    WaitStep
    | MouseMoveStep
    | MouseClickStep
    | KeyPressStep
    | TextInputStep
    | TemplateMatchStep
)


@dataclass(frozen=True, slots=True)
class WorkflowDefinition:
    name: str
    steps: tuple[WorkflowStep, ...]
    target: WindowTarget | None = None
    settings: WorkflowSettings = WorkflowSettings()
