"""Recognize a template, act on its center, and verify the visual result."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import json
from pathlib import Path
import time

import numpy
from PIL import Image, ImageDraw

from maa.controller import Win32Controller

from window_auto.diagnostics.input_test import VisualDifference, calculate_visual_difference
from window_auto.diagnostics.screenshot import bgr_to_image, capture_image
from window_auto.diagnostics.template_match import (
    MatchBox,
    TemplateMatchDiagnosticError,
    recognize_template,
)
from window_auto.runtime.task_runtime import TaskRuntime


class TemplateActionError(RuntimeError):
    """Raised when a recognition-driven action cannot be completed."""


class TemplateNotFoundError(TemplateActionError):
    """Raised before input when the requested template is not found."""


@dataclass(frozen=True, slots=True)
class TemplateActionResult:
    action: str
    point: tuple[int, int]
    click_count: int
    score: float | None
    box: MatchBox
    difference: VisualDifference
    before_path: Path
    after_path: Path
    annotated_path: Path
    difference_path: Path
    report_path: Path


def load_template_image(path: Path) -> numpy.ndarray:
    try:
        with Image.open(path) as image:
            rgb = numpy.asarray(image.convert("RGB"), dtype=numpy.uint8)
    except (OSError, ValueError) as error:
        raise TemplateActionError(f"Failed to load template image {path}: {error}") from error
    return rgb[:, :, [2, 1, 0]].copy()


def action_click_count(action: str) -> int:
    try:
        return {"click": 1, "double-click": 2}[action]
    except KeyError as error:
        raise TemplateActionError(f"Unsupported template action: {action!r}.") from error


def box_center(box: MatchBox) -> tuple[int, int]:
    """Return the match center in recognition-image coordinates used by Maa input."""
    return box.x + box.w // 2, box.y + box.h // 2


def run_template_action(
    runtime: TaskRuntime,
    controller: Win32Controller,
    template: numpy.ndarray,
    threshold: float,
    action: str,
    before_path: Path,
    after_path: Path,
    annotated_path: Path,
    difference_path: Path,
    report_path: Path,
    click_interval_seconds: float = 0.1,
    settle_seconds: float = 0.5,
) -> TemplateActionResult:
    before = capture_image(controller)
    try:
        recognition = recognize_template(runtime, before, template, threshold)
    except TemplateMatchDiagnosticError as error:
        raise TemplateActionError(str(error)) from error
    if not recognition.hit or recognition.box is None:
        raise TemplateNotFoundError("Template was not found; no input was sent.")

    click_count = action_click_count(action)
    point = box_center(recognition.box)

    annotated = bgr_to_image(before)
    draw = ImageDraw.Draw(annotated)
    box = recognition.box
    draw.rectangle(
        (box.x, box.y, box.x + box.w - 1, box.y + box.h - 1),
        outline=(255, 64, 64),
        width=3,
    )
    radius = 5
    draw.ellipse(
        (point[0] - radius, point[1] - radius, point[0] + radius, point[1] + radius),
        outline=(64, 255, 64),
        width=2,
    )

    for click_index in range(click_count):
        job = controller.post_click(*point).wait()
        if not job.succeeded:
            raise TemplateActionError(
                f"MaaFramework click {click_index + 1}/{click_count} failed at {point!r}."
            )
        if click_index + 1 < click_count:
            time.sleep(click_interval_seconds)

    time.sleep(settle_seconds)
    after = capture_image(controller)
    difference, difference_image = calculate_visual_difference(before, after)

    for path in (before_path, after_path, annotated_path, difference_path, report_path):
        path.parent.mkdir(parents=True, exist_ok=True)
    bgr_to_image(before).save(before_path, format="PNG")
    bgr_to_image(after).save(after_path, format="PNG")
    annotated.save(annotated_path, format="PNG")
    Image.fromarray(difference_image, mode="L").save(difference_path, format="PNG")

    report = {
        "action": action,
        "point": list(point),
        "click_count": click_count,
        "score": recognition.score,
        "box": asdict(box),
        "threshold": threshold,
        "difference": asdict(difference),
        "before_path": str(before_path.resolve()),
        "after_path": str(after_path.resolve()),
        "annotated_path": str(annotated_path.resolve()),
        "difference_path": str(difference_path.resolve()),
    }
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    return TemplateActionResult(
        action=action,
        point=point,
        click_count=click_count,
        score=recognition.score,
        box=box,
        difference=difference,
        before_path=before_path.resolve(),
        after_path=after_path.resolve(),
        annotated_path=annotated_path.resolve(),
        difference_path=difference_path.resolve(),
        report_path=report_path.resolve(),
    )
