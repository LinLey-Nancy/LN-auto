"""Safe, explicit double-click input diagnostic with visual verification."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import json
from pathlib import Path
import time

import numpy
from PIL import Image

from maa.controller import Win32Controller

from window_auto.diagnostics.screenshot import bgr_to_image, capture_image


class InputTestError(RuntimeError):
    """Raised when the input test cannot complete safely."""


@dataclass(frozen=True, slots=True)
class VisualDifference:
    mean_absolute_difference: float
    changed_pixel_ratio: float
    visual_change_detected: bool


@dataclass(frozen=True, slots=True)
class InputTestResult:
    point: tuple[int, int]
    click_count: int
    difference: VisualDifference
    before_path: Path
    after_path: Path
    difference_path: Path
    report_path: Path


def calculate_visual_difference(
    before: numpy.ndarray,
    after: numpy.ndarray,
) -> tuple[VisualDifference, numpy.ndarray]:
    if before.shape != after.shape:
        raise InputTestError(
            f"Before/after screenshot shapes differ: {before.shape!r} != {after.shape!r}."
        )
    delta = numpy.abs(before.astype(numpy.int16) - after.astype(numpy.int16)).astype(numpy.uint8)
    per_pixel = delta.max(axis=2)
    changed_pixel_ratio = float(numpy.count_nonzero(per_pixel >= 10) / per_pixel.size)
    mean_difference = float(delta.mean())
    result = VisualDifference(
        mean_absolute_difference=mean_difference,
        changed_pixel_ratio=changed_pixel_ratio,
        visual_change_detected=changed_pixel_ratio >= 0.001,
    )
    return result, per_pixel


def run_input_test(
    controller: Win32Controller,
    point: tuple[int, int],
    before_path: Path,
    after_path: Path,
    difference_path: Path,
    report_path: Path,
    click_count: int = 2,
    click_interval_seconds: float = 0.1,
    settle_seconds: float = 0.5,
) -> InputTestResult:
    x, y = point
    before = capture_image(controller)
    height, width = before.shape[:2]
    if x < 0 or y < 0 or x >= width or y >= height:
        raise InputTestError(f"Click point {point!r} exceeds screenshot size {width}x{height}.")

    if click_count <= 0:
        raise InputTestError("Click count must be positive.")
    for click_index in range(click_count):
        click_job = controller.post_click(x, y).wait()
        if not click_job.succeeded:
            raise InputTestError(
                f"MaaFramework click {click_index + 1}/{click_count} failed at {point!r}."
            )
        if click_index + 1 < click_count:
            time.sleep(click_interval_seconds)
    time.sleep(settle_seconds)
    after = capture_image(controller)

    difference, difference_image = calculate_visual_difference(before, after)
    for path in (before_path, after_path, difference_path, report_path):
        path.parent.mkdir(parents=True, exist_ok=True)
    bgr_to_image(before).save(before_path, format="PNG")
    bgr_to_image(after).save(after_path, format="PNG")
    Image.fromarray(difference_image, mode="L").save(difference_path, format="PNG")

    report = {
        "point": list(point),
        "click_count": click_count,
        "difference": asdict(difference),
        "before_path": str(before_path.resolve()),
        "after_path": str(after_path.resolve()),
        "difference_path": str(difference_path.resolve()),
    }
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return InputTestResult(
        point=point,
        click_count=click_count,
        difference=difference,
        before_path=before_path.resolve(),
        after_path=after_path.resolve(),
        difference_path=difference_path.resolve(),
        report_path=report_path.resolve(),
    )
