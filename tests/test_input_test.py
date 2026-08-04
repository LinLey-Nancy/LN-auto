import unittest
from unittest.mock import patch
from pathlib import Path
import tempfile

import numpy

from window_auto.diagnostics.input_test import calculate_visual_difference, run_input_test


class _SuccessfulJob:
    succeeded = True

    def wait(self):
        return self


class _FakeController:
    def __init__(self) -> None:
        self.clicks: list[tuple[int, int]] = []

    def post_click(self, x: int, y: int) -> _SuccessfulJob:
        self.clicks.append((x, y))
        return _SuccessfulJob()


class InputTestDiagnosticsTests(unittest.TestCase):
    def test_visual_change_is_detected(self) -> None:
        before = numpy.zeros((20, 20, 3), dtype=numpy.uint8)
        after = before.copy()
        after[5:15, 5:15] = 100

        result, difference = calculate_visual_difference(before, after)

        self.assertTrue(result.visual_change_detected)
        self.assertEqual(difference.shape, (20, 20))

    def test_identical_images_have_no_visual_change(self) -> None:
        image = numpy.zeros((20, 20, 3), dtype=numpy.uint8)
        result, _ = calculate_visual_difference(image, image.copy())
        self.assertFalse(result.visual_change_detected)

    def test_input_test_sends_two_click_jobs(self) -> None:
        before = numpy.zeros((20, 20, 3), dtype=numpy.uint8)
        after = before.copy()
        after[5:10, 5:10] = 100
        controller = _FakeController()

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with patch(
                "window_auto.diagnostics.input_test.capture_image",
                side_effect=[before, after],
            ):
                result = run_input_test(
                    controller,
                    (7, 7),
                    root / "before.png",
                    root / "after.png",
                    root / "difference.png",
                    root / "report.json",
                    click_interval_seconds=0,
                    settle_seconds=0,
                )

        self.assertEqual(controller.clicks, [(7, 7), (7, 7)])
        self.assertEqual(result.click_count, 2)
