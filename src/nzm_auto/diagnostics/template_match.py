"""Run a Maa TemplateMatch diagnostic using a crop from the current screenshot."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import json
from pathlib import Path

import numpy
from PIL import ImageDraw

from maa.pipeline import JTemplateMatch

from nzm_auto.diagnostics.screenshot import ScreenshotError, bgr_to_image
from nzm_auto.runtime.task_runtime import TaskRuntime


class TemplateMatchDiagnosticError(RuntimeError):
    """Raised when the template diagnostic cannot be completed."""


@dataclass(frozen=True, slots=True)
class MatchBox:
    x: int
    y: int
    w: int
    h: int


@dataclass(frozen=True, slots=True)
class TemplateRecognitionResult:
    hit: bool
    score: float | None
    box: MatchBox | None
    candidate_score: float | None = None
    candidate_box: MatchBox | None = None


@dataclass(frozen=True, slots=True)
class TemplateMatchDiagnosticResult:
    hit: bool
    score: float | None
    box: MatchBox | None
    annotated_path: Path
    report_path: Path


def match_box_from_raw(raw_box) -> MatchBox:
    if all(hasattr(raw_box, name) for name in ("x", "y", "w", "h")):
        return MatchBox(int(raw_box.x), int(raw_box.y), int(raw_box.w), int(raw_box.h))
    if isinstance(raw_box, (list, tuple)) and len(raw_box) == 4:
        return MatchBox(*(int(value) for value in raw_box))
    if isinstance(raw_box, dict) and all(name in raw_box for name in ("x", "y", "w", "h")):
        return MatchBox(*(int(raw_box[name]) for name in ("x", "y", "w", "h")))
    raise TemplateMatchDiagnosticError(f"Unsupported Maa match box: {raw_box!r}.")


def best_template_candidate(results) -> tuple[float | None, MatchBox | None]:
    """Return the highest-scoring candidate, including below-threshold misses."""
    best_score: float | None = None
    best_box: MatchBox | None = None
    for result in results or ():
        raw_score = getattr(result, "score", None)
        raw_box = getattr(result, "box", None)
        if raw_score is None or raw_box is None:
            continue
        score = float(raw_score)
        if best_score is None or score > best_score:
            best_score = score
            best_box = match_box_from_raw(raw_box)
    return best_score, best_box


def crop_template(image: numpy.ndarray, roi: tuple[int, int, int, int]) -> numpy.ndarray:
    x, y, width, height = roi
    image_height, image_width = image.shape[:2]
    if x < 0 or y < 0 or width <= 0 or height <= 0:
        raise TemplateMatchDiagnosticError("Template ROI must use non-negative x/y and positive size.")
    if x + width > image_width or y + height > image_height:
        raise TemplateMatchDiagnosticError(
            f"Template ROI {roi!r} exceeds screenshot size {image_width}x{image_height}."
        )
    return image[y : y + height, x : x + width].copy()


def recognize_template(
    runtime: TaskRuntime,
    image: numpy.ndarray,
    template: numpy.ndarray,
    threshold: float,
) -> TemplateRecognitionResult:
    if not 0.0 < threshold <= 1.0:
        raise TemplateMatchDiagnosticError("Template threshold must be greater than 0 and at most 1.")

    resource_name = "__diagnostic_template__.png"
    if not runtime.resource.override_image(resource_name, template):
        raise TemplateMatchDiagnosticError("Failed to inject the temporary template into Maa Resource.")

    job = runtime.tasker.post_recognition(
        "TemplateMatch",
        JTemplateMatch(template=[resource_name], threshold=[threshold]),
        image,
    ).wait()
    if not job.succeeded:
        raise TemplateMatchDiagnosticError("Maa TemplateMatch recognition job failed.")

    task_detail = job.get()
    if task_detail is None or not task_detail.nodes:
        raise TemplateMatchDiagnosticError("Maa returned no recognition node detail.")
    recognition = task_detail.nodes[-1].recognition
    if recognition is None:
        raise TemplateMatchDiagnosticError("Maa returned no recognition detail.")

    best_result = recognition.best_result
    box = None
    score = None
    if best_result is not None:
        box = match_box_from_raw(best_result.box)
        score = float(best_result.score)

    candidate_score, candidate_box = best_template_candidate(
        getattr(recognition, "all_results", None)
    )
    return TemplateRecognitionResult(
        bool(recognition.hit),
        score,
        box,
        candidate_score,
        candidate_box,
    )


def run_template_match(
    runtime: TaskRuntime,
    image: numpy.ndarray,
    template_roi: tuple[int, int, int, int],
    threshold: float,
    annotated_path: Path,
    report_path: Path,
) -> TemplateMatchDiagnosticResult:
    template = crop_template(image, template_roi)
    recognition = recognize_template(runtime, image, template, threshold)

    annotated = bgr_to_image(image)
    if recognition.box is not None:
        box = recognition.box
        draw = ImageDraw.Draw(annotated)
        draw.rectangle(
            (box.x, box.y, box.x + box.w - 1, box.y + box.h - 1),
            outline=(255, 64, 64),
            width=3,
        )
    annotated_path.parent.mkdir(parents=True, exist_ok=True)
    annotated.save(annotated_path, format="PNG")

    report = {
        "hit": recognition.hit,
        "score": recognition.score,
        "box": asdict(recognition.box) if recognition.box else None,
        "template_roi": list(template_roi),
        "threshold": threshold,
        "annotated_path": str(annotated_path.resolve()),
    }
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    return TemplateMatchDiagnosticResult(
        hit=recognition.hit,
        score=recognition.score,
        box=recognition.box,
        annotated_path=annotated_path.resolve(),
        report_path=report_path.resolve(),
    )
