import unittest
from unittest.mock import patch

import numpy
from PIL import Image

from window_auto.diagnostics.desktop_scope import (
    DesktopCoordinateError,
    DesktopRecognitionFrame,
    capture_desktop_recognition_frame,
    desktop_box_to_controller,
    desktop_point_to_controller,
    scale_box_between_sizes,
)
from window_auto.diagnostics.template_match import MatchBox


def _frame() -> DesktopRecognitionFrame:
    return DesktopRecognitionFrame(
        image=numpy.zeros((720, 1280, 3), dtype=numpy.uint8),
        raw_size=(1920, 1080),
        recognition_size=(1280, 720),
    )


class DesktopScopeTests(unittest.TestCase):
    def test_window_match_scales_from_recognition_to_raw_input_size(self) -> None:
        box = scale_box_between_sizes(
            MatchBox(10, 20, 30, 40),
            source_size=(1280, 720),
            target_size=(1920, 1080),
        )

        self.assertEqual((box.x + box.w // 2, box.y + box.h // 2), (38, 60))
        self.assertEqual((box.w, box.h), (45, 60))

    def test_desktop_capture_scales_to_long_side(self) -> None:
        with patch(
            "window_auto.diagnostics.desktop_scope.ImageGrab.grab",
            return_value=Image.new("RGB", (1920, 1080), (1, 2, 3)),
        ):
            frame = capture_desktop_recognition_frame(1280)

        self.assertEqual(frame.raw_size, (1920, 1080))
        self.assertEqual(frame.recognition_size, (1280, 720))
        self.assertEqual(frame.image.shape, (720, 1280, 3))

    def test_full_desktop_window_mapping_scales_to_raw_input(self) -> None:
        point = desktop_point_to_controller(
            (1140, 632),
            _frame(),
            client_origin=(0, 0),
            client_size=(1920, 1080),
            controller_input_size=(1920, 1080),
        )

        self.assertEqual(point, (1710, 948))

    def test_desktop_point_maps_into_offset_window(self) -> None:
        point = desktop_point_to_controller(
            (200, 120),
            _frame(),
            client_origin=(100, 100),
            client_size=(800, 600),
            controller_input_size=(800, 600),
        )

        self.assertEqual(point, (200, 80))

    def test_desktop_box_keeps_mapped_center(self) -> None:
        box = desktop_box_to_controller(
            MatchBox(195, 115, 10, 10),
            _frame(),
            client_origin=(100, 100),
            client_size=(800, 600),
            controller_input_size=(800, 600),
        )

        self.assertEqual((box.x + box.w // 2, box.y + box.h // 2), (200, 80))

    def test_point_outside_window_is_rejected(self) -> None:
        with self.assertRaises(DesktopCoordinateError):
            desktop_point_to_controller(
                (10, 10),
                _frame(),
                client_origin=(100, 100),
                client_size=(800, 600),
                controller_input_size=(800, 600),
            )


if __name__ == "__main__":
    unittest.main()
