"""Run a Maa OCR recognition against the current screenshot."""

from __future__ import annotations

from dataclasses import dataclass

import numpy

from maa.pipeline import JOCR

from window_auto.diagnostics.template_match import MatchBox, match_box_from_raw
from window_auto.runtime.task_runtime import TaskRuntime


class OcrMatchDiagnosticError(RuntimeError):
    """Raised when the OCR recognition cannot be completed."""


@dataclass(frozen=True, slots=True)
class OcrRecognitionResult:
    hit: bool
    score: float | None
    box: MatchBox | None
    text: str | None = None


def recognize_ocr(
    runtime: TaskRuntime,
    image: numpy.ndarray,
    expected: tuple[str, ...],
    threshold: float,
) -> OcrRecognitionResult:
    if not expected:
        raise OcrMatchDiagnosticError("OCR expected text list must not be empty.")
    if not 0.0 < threshold <= 1.0:
        raise OcrMatchDiagnosticError("OCR threshold must be greater than 0 and at most 1.")

    job = runtime.tasker.post_recognition(
        "OCR",
        JOCR(expected=list(expected), threshold=threshold),
        image,
    ).wait()
    if not job.succeeded:
        raise OcrMatchDiagnosticError("Maa OCR recognition job failed.")

    task_detail = job.get()
    if task_detail is None or not task_detail.nodes:
        raise OcrMatchDiagnosticError("Maa returned no recognition node detail.")
    recognition = task_detail.nodes[-1].recognition
    if recognition is None:
        raise OcrMatchDiagnosticError("Maa returned no recognition detail.")

    best_result = recognition.best_result
    box = None
    score = None
    text = None
    if best_result is not None:
        box = match_box_from_raw(best_result.box)
        score = float(best_result.score)
        text = str(best_result.text)
    return OcrRecognitionResult(bool(recognition.hit), score, box, text)
