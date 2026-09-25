import unittest
from unittest.mock import Mock, patch

from window_auto.runtime.win32_input import DirectInputError, click_client_point


class _Window:
    hwnd = 0x1234


def _fake_user32(hwnd: int) -> Mock:
    user32 = Mock()
    user32.IsWindow.return_value = True
    user32.IsIconic.return_value = False
    user32.GetForegroundWindow.return_value = hwnd

    def get_client_rect(_hwnd, rect_ptr) -> bool:
        rect = rect_ptr._obj
        rect.left, rect.top, rect.right, rect.bottom = 0, 0, 100, 100
        return True

    user32.GetClientRect.side_effect = get_client_rect
    user32.ClientToScreen.return_value = True
    user32.SetCursorPos.return_value = True

    def get_cursor_pos(point_ptr) -> bool:
        point = point_ptr._obj
        point.x, point.y = 10, 10
        return True

    user32.GetCursorPos.side_effect = get_cursor_pos
    return user32


class ClickClientPointMessageTests(unittest.TestCase):
    def _run_with(self, user32: Mock) -> str:
        with patch(
            "window_auto.runtime.win32_input.ctypes.WinDLL", return_value=user32
        ):
            with self.assertRaises(DirectInputError) as raised:
                click_client_point(_Window(), (10, 10), "left")
        return str(raised.exception)

    def test_cursor_position_refusal_suggests_running_as_administrator(self) -> None:
        user32 = _fake_user32(_Window.hwnd)
        user32.SetCursorPos.return_value = False

        message = self._run_with(user32)

        self.assertIn("未发送点击", message)
        self.assertIn("管理员身份", message)

    def test_foreground_refusal_is_chinese_and_actionable(self) -> None:
        user32 = _fake_user32(_Window.hwnd)
        user32.GetForegroundWindow.return_value = 0

        message = self._run_with(user32)

        self.assertIn("前台", message)
        self.assertIn("未发送点击", message)
        self.assertNotIn("Windows did not allow", message)

    def test_out_of_bounds_point_is_chinese_and_actionable(self) -> None:
        user32 = _fake_user32(_Window.hwnd)

        with patch(
            "window_auto.runtime.win32_input.ctypes.WinDLL", return_value=user32
        ):
            with self.assertRaises(DirectInputError) as raised:
                click_client_point(_Window(), (500, 10), "left")

        message = str(raised.exception)
        self.assertIn("超出", message)
        self.assertIn("未发送点击", message)
        self.assertNotIn("outside", message)


if __name__ == "__main__":
    unittest.main()
