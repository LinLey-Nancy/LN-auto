import unittest

import numpy

from window_auto.runtime.win32_controller import (
    ControllerConnectionError,
    combine_screencap_methods,
    connect_controller,
    parse_input_method,
)


class _SuccessfulJob:
    succeeded = True

    def __init__(self, result=None) -> None:
        self.result = result

    def wait(self):
        return self

    def get(self):
        return self.result


class _FakeController:
    connected = True

    def __init__(
        self,
        raw_resolution: tuple[int, int] = (1920, 1080),
        screenshot_resolution: tuple[int, int] = (1280, 720),
    ) -> None:
        self.resolution = raw_resolution
        self.mouse_lock_follow: bool | None = None
        width, height = screenshot_resolution
        self.screenshot = numpy.zeros((height, width, 3), dtype=numpy.uint8)

    def post_connection(self):
        return _SuccessfulJob()

    def post_screencap(self):
        return _SuccessfulJob(self.screenshot)

    def set_mouse_lock_follow(self, enabled: bool):
        self.mouse_lock_follow = enabled
        return True


CONTROLLER_CONFIG = {
    "screenshot_target_long_side": 1280,
    "expected_raw_resolution": [1920, 1080],
    "expected_screenshot_resolution": [1280, 720],
}

AUTO_CONTROLLER_CONFIG = {
    "screenshot_target_long_side": 1280,
    "expected_raw_resolution": None,
    "expected_screenshot_resolution": None,
}


class Win32ControllerConfigTests(unittest.TestCase):
    def test_background_screencap_methods_are_combined(self) -> None:
        self.assertEqual(combine_screencap_methods(["FramePool", "PrintWindow"]), 18)

    def test_post_message_input_is_parsed(self) -> None:
        self.assertEqual(parse_input_method("PostMessage"), 4)

    def test_unknown_screencap_method_is_rejected(self) -> None:
        with self.assertRaises(ControllerConnectionError):
            combine_screencap_methods(["Unknown"])

    def test_matching_resolution_passes_startup_check(self) -> None:
        connect_controller(_FakeController(), CONTROLLER_CONFIG)

    def test_raw_resolution_mismatch_is_rejected_before_input(self) -> None:
        controller = _FakeController(raw_resolution=(2560, 1440))
        with self.assertRaisesRegex(ControllerConnectionError, "Raw resolution"):
            connect_controller(controller, CONTROLLER_CONFIG)

    def test_screenshot_resolution_mismatch_is_rejected_before_input(self) -> None:
        controller = _FakeController(screenshot_resolution=(1280, 800))
        with self.assertRaisesRegex(ControllerConnectionError, "Screenshot resolution"):
            connect_controller(controller, CONTROLLER_CONFIG)

    def test_auto_resolution_allows_other_raw_sizes(self) -> None:
        controller = _FakeController(raw_resolution=(2560, 1440))

        raw, screenshot = connect_controller(controller, AUTO_CONTROLLER_CONFIG)

        self.assertEqual(raw, (2560, 1440))
        self.assertEqual(screenshot, (1280, 720))

    def test_auto_resolution_still_checks_screenshot_long_side(self) -> None:
        controller = _FakeController(screenshot_resolution=(1920, 1080))
        with self.assertRaisesRegex(ControllerConnectionError, "target long side"):
            connect_controller(controller, AUTO_CONTROLLER_CONFIG)

    def test_desktop_scope_skips_window_raw_requirement(self) -> None:
        config = {
            "screenshot_target_long_side": 1280,
            "capture_scope": "desktop",
            "expected_raw_resolution": [1920, 1080],
            "expected_screenshot_resolution": [1280, 720],
        }
        controller = _FakeController(raw_resolution=(1366, 768))

        raw, _ = connect_controller(controller, config)

        self.assertEqual(raw, (1366, 768))

    def test_mouse_lock_follow_is_enabled_after_connection(self) -> None:
        config = {
            **CONTROLLER_CONFIG,
            "mouse_input": "PostMessage",
            "mouse_lock_follow": True,
        }
        controller = _FakeController()

        connect_controller(controller, config)

        self.assertTrue(controller.mouse_lock_follow)
