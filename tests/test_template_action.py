from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import numpy
from PIL import Image

from window_auto.automation.template_action import (
    TemplateActionError,
    action_click_count,
    box_center,
    load_template_image,
    run_template_action,
)
from window_auto.diagnostics.template_match import MatchBox, TemplateRecognitionResult


class _SuccessfulJob:
    succeeded = True

    def wait(self):
        return self


class _FakeController:
    def __init__(self, resolution: tuple[int, int] = (40, 30)) -> None:
        self.clicks: list[tuple[int, int]] = []
        self.resolution = resolution

    def post_click(self, x: int, y: int) -> _SuccessfulJob:
        self.clicks.append((x, y))
        return _SuccessfulJob()


class TemplateActionTests(unittest.TestCase):
    def test_box_center_uses_match_center(self) -> None:
        self.assertEqual(box_center(MatchBox(10, 20, 30, 40)), (25, 40))

    def test_unsupported_action_is_rejected(self) -> None:
        with self.assertRaises(TemplateActionError):
            action_click_count("drag")

    def test_template_png_is_loaded_as_bgr(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "template.png"
            Image.new("RGB", (2, 1), (10, 20, 30)).save(path)

            template = load_template_image(path)

        self.assertEqual(template.shape, (1, 2, 3))
        self.assertEqual(tuple(template[0, 0]), (30, 20, 10))

    def test_recognized_center_drives_double_click(self) -> None:
        before = numpy.zeros((30, 40, 3), dtype=numpy.uint8)
        after = before.copy()
        after[5:20, 10:30] = 100
        controller = _FakeController()
        recognition = TemplateRecognitionResult(True, 0.95, MatchBox(10, 5, 20, 15))

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with (
                patch(
                    "window_auto.automation.template_action.capture_image",
                    side_effect=[before, after],
                ),
                patch(
                    "window_auto.automation.template_action.recognize_template",
                    return_value=recognition,
                ),
            ):
                result = run_template_action(
                    object(),
                    controller,
                    numpy.zeros((5, 5, 3), dtype=numpy.uint8),
                    0.8,
                    "double-click",
                    root / "before.png",
                    root / "after.png",
                    root / "target.png",
                    root / "difference.png",
                    root / "report.json",
                    click_interval_seconds=0,
                    settle_seconds=0,
                )

        self.assertEqual(controller.clicks, [(20, 12), (20, 12)])
        self.assertEqual(result.point, (20, 12))
        self.assertEqual(result.input_point, (20, 12))
        self.assertTrue(result.difference.visual_change_detected)

    def test_recognized_center_is_scaled_to_raw_controller_coordinates(self) -> None:
        before = numpy.zeros((30, 40, 3), dtype=numpy.uint8)
        after = before.copy()
        after[5:20, 10:30] = 100
        controller = _FakeController(resolution=(80, 60))
        recognition = TemplateRecognitionResult(True, 0.95, MatchBox(10, 5, 20, 15))

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with (
                patch(
                    "window_auto.automation.template_action.capture_image",
                    side_effect=[before, after],
                ),
                patch(
                    "window_auto.automation.template_action.recognize_template",
                    return_value=recognition,
                ),
            ):
                result = run_template_action(
                    object(),
                    controller,
                    numpy.zeros((5, 5, 3), dtype=numpy.uint8),
                    0.8,
                    "click",
                    root / "before.png",
                    root / "after.png",
                    root / "target.png",
                    root / "difference.png",
                    root / "report.json",
                    click_interval_seconds=0,
                    settle_seconds=0,
                )

        self.assertEqual(result.point, (20, 12))
        self.assertEqual(result.input_point, (40, 24))
        self.assertEqual(controller.clicks, [(40, 24)])

    def test_missing_template_sends_no_input(self) -> None:
        controller = _FakeController()
        screenshot = numpy.zeros((20, 20, 3), dtype=numpy.uint8)
        recognition = TemplateRecognitionResult(False, None, None)

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with (
                patch(
                    "window_auto.automation.template_action.capture_image",
                    return_value=screenshot,
                ),
                patch(
                    "window_auto.automation.template_action.recognize_template",
                    return_value=recognition,
                ),
            ):
                with self.assertRaises(TemplateActionError):
                    run_template_action(
                        object(),
                        controller,
                        screenshot,
                        0.8,
                        "click",
                        root / "before.png",
                        root / "after.png",
                        root / "target.png",
                        root / "difference.png",
                        root / "report.json",
                        settle_seconds=0,
                    )

        self.assertEqual(controller.clicks, [])
