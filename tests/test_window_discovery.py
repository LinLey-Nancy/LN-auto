import unittest
from unittest.mock import patch

from window_auto.windowing.discovery import (
    WindowInfo,
    desktop_window_info,
    find_windows,
    matches_filters,
    physical_cursor_pos,
)
from window_auto.windowing.selector import (
    AmbiguousWindowError,
    WindowNotFoundError,
    WindowIndexError,
    choose_window_by_index,
    require_unique_window,
)


class WindowFilterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.window = WindowInfo(
            hwnd=123,
            title="Example Application",
            class_name="ApplicationWindowClass",
            window_width=1920,
            window_height=1080,
            client_width=1920,
            client_height=1080,
            visible=True,
            minimized=False,
        )

    def test_title_filter_is_case_insensitive(self) -> None:
        self.assertTrue(matches_filters(self.window, title_filter="example"))

    def test_client_origin_defaults_and_serializes(self) -> None:
        data = self.window.to_dict()

        self.assertIsNone(self.window.client_x)
        self.assertIsNone(self.window.client_y)
        self.assertIn("client_x", data)
        self.assertIn("client_y", data)

    def test_class_filter_rejects_non_match(self) -> None:
        self.assertFalse(matches_filters(self.window, class_filter="browser"))

    def test_unique_window_is_selected(self) -> None:
        selected = require_unique_window(
            [self.window], title_filter="Example", class_filter=None
        )
        self.assertIs(selected, self.window)

    def test_no_window_is_rejected(self) -> None:
        with self.assertRaises(WindowNotFoundError):
            require_unique_window([], title_filter="Example", class_filter=None)

    def test_multiple_windows_are_rejected(self) -> None:
        with self.assertRaises(AmbiguousWindowError):
            require_unique_window(
                [self.window, self.window], title_filter="Example", class_filter=None
            )

    def test_window_can_be_chosen_by_index(self) -> None:
        self.assertIs(choose_window_by_index([self.window], 0), self.window)

    def test_invalid_window_index_is_rejected(self) -> None:
        with self.assertRaises(WindowIndexError):
            choose_window_by_index([self.window], 1)

    def test_null_handles_are_skipped_during_enumeration(self) -> None:
        fake_desktop_windows = [
            type("W", (), {"hwnd": None, "window_name": "ghost", "class_name": "X"})(),
            type("W", (), {"hwnd": 0, "window_name": "zero", "class_name": "X"})(),
            type("W", (), {"hwnd": 0x10, "window_name": "real", "class_name": "X"})(),
        ]
        with patch(
            "maa.toolkit.Toolkit.find_desktop_windows",
            return_value=fake_desktop_windows,
        ):
            windows = find_windows()

        self.assertEqual([window.title for window in windows], ["real"])
        self.assertEqual(windows[0].hwnd, 0x10)

    def test_desktop_window_info_covers_the_primary_screen(self) -> None:
        desktop = desktop_window_info()

        self.assertNotEqual(desktop.hwnd, 0)
        self.assertEqual(desktop.title, "整个屏幕")
        self.assertTrue(desktop.visible)
        self.assertFalse(desktop.minimized)
        self.assertIsNotNone(desktop.client_width)
        self.assertIsNotNone(desktop.client_height)
        self.assertGreater(desktop.client_width, 0)
        self.assertGreater(desktop.client_height, 0)
        self.assertEqual((desktop.client_x, desktop.client_y), (0, 0))

    def test_physical_cursor_pos_returns_screen_coordinates(self) -> None:
        position = physical_cursor_pos()

        self.assertIsNotNone(position)
        x, y = position
        self.assertGreaterEqual(x, 0)
        self.assertGreaterEqual(y, 0)


if __name__ == "__main__":
    unittest.main()
