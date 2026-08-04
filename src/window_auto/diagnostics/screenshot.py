"""Capture and save MaaFramework screenshots as PNG files."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy
from PIL import Image

from maa.controller import Win32Controller


class ScreenshotError(RuntimeError):
    """Raised when a screenshot cannot be captured or saved."""


@dataclass(frozen=True, slots=True)
class ScreenshotResult:
    path: Path
    width: int
    height: int
    channels: int


def bgr_to_image(image: numpy.ndarray) -> Image.Image:
    if image.ndim != 3 or image.shape[2] not in (3, 4):
        raise ScreenshotError(f"Unsupported screenshot shape: {image.shape!r}.")
    if image.size == 0:
        raise ScreenshotError("MaaFramework returned an empty screenshot.")

    if image.shape[2] == 3:
        converted = image[:, :, [2, 1, 0]]
        return Image.fromarray(converted, mode="RGB")

    converted = image[:, :, [2, 1, 0, 3]]
    return Image.fromarray(converted, mode="RGBA")


def capture_screenshot(controller: Win32Controller, output_path: Path) -> ScreenshotResult:
    image = capture_image(controller)
    try:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        bgr_to_image(image).save(output_path, format="PNG")
    except ScreenshotError:
        raise
    except (OSError, RuntimeError, ValueError) as error:
        raise ScreenshotError(f"Failed to capture or save screenshot: {error}") from error

    height, width, channels = image.shape
    return ScreenshotResult(output_path.resolve(), width, height, channels)


def capture_image(controller: Win32Controller) -> numpy.ndarray:
    try:
        job = controller.post_screencap().wait()
        if not job.succeeded:
            raise ScreenshotError("MaaFramework screenshot job failed.")
        image = job.get()
    except ScreenshotError:
        raise
    except (OSError, RuntimeError, ValueError) as error:
        raise ScreenshotError(f"Failed to capture screenshot: {error}") from error

    if image.ndim != 3 or image.shape[2] not in (3, 4) or image.size == 0:
        raise ScreenshotError(f"MaaFramework returned an invalid screenshot: {image.shape!r}.")
    return image
