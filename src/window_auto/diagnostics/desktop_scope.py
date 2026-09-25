"""Capture the whole desktop and map desktop matches back to a target window."""

from __future__ import annotations

from dataclasses import dataclass

import numpy
from PIL import Image, ImageGrab

from window_auto.diagnostics.template_match import MatchBox


class DesktopCoordinateError(RuntimeError):
    """Raised when a desktop match cannot be mapped inside the target window."""


@dataclass(frozen=True, slots=True)
class DesktopRecognitionFrame:
    image: numpy.ndarray
    raw_size: tuple[int, int]
    recognition_size: tuple[int, int]


def scale_point_between_sizes(
    point: tuple[int, int],
    source_size: tuple[int, int],
    target_size: tuple[int, int],
) -> tuple[int, int]:
    """Map a point between coordinate spaces, e.g. scaled screenshot to raw input."""
    source_width, source_height = source_size
    target_width, target_height = target_size
    if min(source_width, source_height, target_width, target_height) <= 0:
        raise DesktopCoordinateError("Coordinate-space sizes must be positive.")
    return (
        round(point[0] * target_width / source_width),
        round(point[1] * target_height / source_height),
    )


def scale_box_between_sizes(
    box: MatchBox,
    source_size: tuple[int, int],
    target_size: tuple[int, int],
) -> MatchBox:
    """Scale a match box while preserving its center in the target space."""
    source_width, source_height = source_size
    target_width, target_height = target_size
    if min(source_width, source_height, target_width, target_height) <= 0:
        raise DesktopCoordinateError("Coordinate-space sizes must be positive.")
    center_x = box.x + box.w / 2
    center_y = box.y + box.h / 2
    target_center_x = round(center_x * target_width / source_width)
    target_center_y = round(center_y * target_height / source_height)
    target_box_width = max(1, round(box.w * target_width / source_width))
    target_box_height = max(1, round(box.h * target_height / source_height))
    return MatchBox(
        target_center_x - target_box_width // 2,
        target_center_y - target_box_height // 2,
        target_box_width,
        target_box_height,
    )


def capture_desktop_recognition_frame(long_side: int) -> DesktopRecognitionFrame:
    if long_side <= 0:
        raise DesktopCoordinateError("Desktop recognition long side must be positive.")
    screenshot = ImageGrab.grab().convert("RGB")
    rgb = numpy.asarray(screenshot, dtype=numpy.uint8)
    raw = rgb[:, :, [2, 1, 0]].copy()
    raw_height, raw_width = raw.shape[:2]
    if raw_width <= 0 or raw_height <= 0:
        raise DesktopCoordinateError("Desktop screenshot is empty.")

    scale = long_side / max(raw_width, raw_height)
    recognition_width = max(1, round(raw_width * scale))
    recognition_height = max(1, round(raw_height * scale))
    if (recognition_width, recognition_height) == (raw_width, raw_height):
        recognition = raw
    else:
        resized = screenshot.resize(
            (recognition_width, recognition_height),
            Image.Resampling.LANCZOS,
        )
        resized_rgb = numpy.asarray(resized.convert("RGB"), dtype=numpy.uint8)
        recognition = resized_rgb[:, :, [2, 1, 0]].copy()

    return DesktopRecognitionFrame(
        image=recognition,
        raw_size=(raw_width, raw_height),
        recognition_size=(recognition_width, recognition_height),
    )


def desktop_point_to_controller(
    point: tuple[int, int],
    frame: DesktopRecognitionFrame,
    client_origin: tuple[int, int],
    client_size: tuple[int, int],
    controller_input_size: tuple[int, int],
) -> tuple[int, int]:
    recognition_width, recognition_height = frame.recognition_size
    raw_width, raw_height = frame.raw_size
    client_width, client_height = client_size
    controller_width, controller_height = controller_input_size
    if min(recognition_width, recognition_height, raw_width, raw_height) <= 0:
        raise DesktopCoordinateError("Desktop frame sizes must be positive.")
    if client_width <= 0 or client_height <= 0:
        raise DesktopCoordinateError("Target window client size must be positive.")
    if controller_width <= 0 or controller_height <= 0:
        raise DesktopCoordinateError("Controller image size must be positive.")

    screen_x = point[0] * raw_width / recognition_width
    screen_y = point[1] * raw_height / recognition_height
    client_x = screen_x - client_origin[0]
    client_y = screen_y - client_origin[1]
    if (
        client_x < 0
        or client_y < 0
        or client_x >= client_width
        or client_y >= client_height
    ):
        raise DesktopCoordinateError(
            f"Desktop match maps outside the target window client area: "
            f"client=({client_x:.1f},{client_y:.1f}), size={client_size!r}."
        )

    input_x = round(client_x * controller_width / client_width)
    input_y = round(client_y * controller_height / client_height)
    return (
        min(max(input_x, 0), controller_width - 1),
        min(max(input_y, 0), controller_height - 1),
    )


def desktop_box_to_controller(
    box: MatchBox,
    frame: DesktopRecognitionFrame,
    client_origin: tuple[int, int],
    client_size: tuple[int, int],
    controller_input_size: tuple[int, int],
) -> MatchBox:
    center = (box.x + box.w // 2, box.y + box.h // 2)
    input_center = desktop_point_to_controller(
        center,
        frame,
        client_origin,
        client_size,
        controller_input_size,
    )
    recognition_width, recognition_height = frame.recognition_size
    raw_width, raw_height = frame.raw_size
    client_width, client_height = client_size
    controller_width, controller_height = controller_input_size
    scale_x = (raw_width / recognition_width) * (controller_width / client_width)
    scale_y = (raw_height / recognition_height) * (controller_height / client_height)
    input_width = max(1, round(box.w * scale_x))
    input_height = max(1, round(box.h * scale_y))
    return MatchBox(
        input_center[0] - input_width // 2,
        input_center[1] - input_height // 2,
        input_width,
        input_height,
    )
