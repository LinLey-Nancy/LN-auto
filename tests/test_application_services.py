from pathlib import Path
import unittest
from unittest.mock import Mock, patch

from window_auto.application.input_profiles import (
    InputProfileName,
    RunMode,
    default_input_profile,
    get_input_profile,
    mode_controller_overrides,
    mode_input_profiles,
    parse_run_mode,
)
from window_auto.application.session import AutomationSession
from window_auto.application.window_service import WindowQuery, choose_window, list_windows
from window_auto.diagnostics.workspace import DebugWorkspace
from window_auto.windowing.discovery import WindowInfo


def _window(hwnd: int, *, visible: bool = True) -> WindowInfo:
    return WindowInfo(
        hwnd=hwnd,
        title=f"Window {hwnd}",
        class_name="TestWindow",
        window_width=1920,
        window_height=1080,
        client_width=1920,
        client_height=1080,
        visible=visible,
        minimized=False,
    )


def _config() -> dict:
    return {
        "controller": {
            "mouse_input": "PostMessage",
            "keyboard_input": "PostMessage",
        },
        "runtime": {"resource_path": "assets/resource"},
    }


class WindowServiceTests(unittest.TestCase):
    @patch("window_auto.application.window_service.find_windows")
    def test_list_windows_applies_query_and_visibility(self, find_windows: Mock) -> None:
        unnamed = _window(3)
        unnamed = WindowInfo(
            **{
                **unnamed.to_dict(),
                "title": "   ",
            }
        )
        find_windows.return_value = [
            _window(1),
            _window(2, visible=False),
            unnamed,
        ]

        result = list_windows(WindowQuery("title", "class", visible_only=True))

        self.assertEqual([window.hwnd for window in result], [1])
        find_windows.assert_called_once_with(
            title_filter="title",
            class_filter="class",
        )

    @patch("window_auto.application.window_service.find_windows")
    def test_choose_window_selects_query_result_by_index(self, find_windows: Mock) -> None:
        find_windows.return_value = [_window(10), _window(20)]

        selected = choose_window(WindowQuery(), 1)

        self.assertEqual(selected.hwnd, 20)


class InputProfileTests(unittest.TestCase):
    def test_foreground_profile_uses_seize_for_mouse_and_keyboard(self) -> None:
        profile = get_input_profile(InputProfileName.FOREGROUND_COMPATIBLE)

        self.assertEqual(profile.mouse_method, "Seize")
        self.assertEqual(profile.keyboard_method, "Seize")
        self.assertFalse(profile.supports_background)

    def test_background_profile_requires_observable_verification(self) -> None:
        profile = get_input_profile("background-message")

        self.assertIn("忽略模拟输入", profile.warning)

    def test_background_window_profile_targets_locked_mouse_window(self) -> None:
        profile = get_input_profile(InputProfileName.BACKGROUND_WINDOW_MESSAGE)

        self.assertEqual(profile.mouse_method, "PostMessage")
        self.assertEqual(profile.keyboard_method, "PostMessage")
        self.assertTrue(profile.supports_background)
        self.assertTrue(profile.mouse_lock_follow)
        self.assertFalse(profile.direct_screen_input)

    def test_precise_foreground_profile_uses_direct_screen_coordinates(self) -> None:
        profile = get_input_profile(InputProfileName.FOREGROUND_PRECISE)

        self.assertEqual(profile.mouse_method, "PostMessage")
        self.assertEqual(profile.keyboard_method, "Seize")
        self.assertFalse(profile.supports_background)
        self.assertTrue(profile.direct_screen_input)


class RunModeTests(unittest.TestCase):
    def test_parse_run_mode_falls_back_to_window(self) -> None:
        self.assertEqual(parse_run_mode("fullscreen"), RunMode.FULLSCREEN)
        self.assertEqual(parse_run_mode("garbage"), RunMode.WINDOW)
        self.assertEqual(parse_run_mode(None), RunMode.WINDOW)

    def test_window_mode_offers_all_profiles(self) -> None:
        profiles = mode_input_profiles(RunMode.WINDOW)

        self.assertEqual(len(profiles), 5)
        self.assertIn(InputProfileName.BACKGROUND_MESSAGE, profiles)
        self.assertEqual(
            default_input_profile(RunMode.WINDOW), InputProfileName.FOREGROUND_PRECISE
        )

    def test_fullscreen_mode_only_offers_foreground_profiles(self) -> None:
        profiles = mode_input_profiles(RunMode.FULLSCREEN)

        self.assertEqual(
            list(profiles),
            [InputProfileName.FOREGROUND_COMPATIBLE, InputProfileName.DRIVER_INTERCEPTION],
        )
        for name in profiles:
            self.assertFalse(get_input_profile(name).supports_background)
            self.assertFalse(get_input_profile(name).direct_screen_input)
        self.assertEqual(
            default_input_profile(RunMode.FULLSCREEN),
            InputProfileName.FOREGROUND_COMPATIBLE,
        )

    def test_window_mode_overrides_use_window_scope(self) -> None:
        overrides = mode_controller_overrides(RunMode.WINDOW)

        self.assertEqual(overrides["screencap_mode"], "background")
        self.assertEqual(overrides["capture_scope"], "window")

    def test_fullscreen_mode_overrides_use_screen_level_capture(self) -> None:
        overrides = mode_controller_overrides(RunMode.FULLSCREEN)

        self.assertEqual(overrides["screencap_mode"], "foreground")
        self.assertEqual(overrides["capture_scope"], "desktop")
        self.assertEqual(
            overrides["foreground_screencap"], ["DXGI_DesktopDup", "ScreenDC"]
        )


class AutomationSessionTests(unittest.TestCase):
    @patch("window_auto.application.session.connect_controller")
    @patch("window_auto.application.session.create_controller")
    def test_connect_can_override_mouse_input(
        self,
        create_controller: Mock,
        connect_controller: Mock,
    ) -> None:
        controller = Mock()
        create_controller.return_value = controller
        connect_controller.return_value = ((1920, 1080), (1280, 720))
        workspace = DebugWorkspace(Path("debug"))

        session = AutomationSession.connect(
            _window(1),
            _config(),
            Path("."),
            workspace,
            mouse_input="Seize",
            keyboard_input="SendMessage",
            mouse_lock_follow=True,
            direct_screen_input=True,
        )

        used_config = create_controller.call_args.args[1]
        self.assertEqual(used_config["mouse_input"], "Seize")
        self.assertEqual(used_config["keyboard_input"], "SendMessage")
        self.assertTrue(used_config["mouse_lock_follow"])
        self.assertTrue(used_config["direct_screen_input"])
        connect_controller.assert_called_once_with(controller, used_config)
        self.assertEqual(session.config["controller"]["mouse_input"], "Seize")
        self.assertEqual(session.config["controller"]["keyboard_input"], "SendMessage")
        self.assertTrue(session.config["controller"]["mouse_lock_follow"])
        self.assertTrue(session.config["controller"]["direct_screen_input"])
        self.assertEqual(session.window.hwnd, 1)
        self.assertEqual(session.controller_raw_size, (1920, 1080))
        self.assertEqual(session.controller_image_size, (1280, 720))

    @patch("window_auto.application.session.load_task_runtime")
    def test_runtime_is_initialized_once(self, load_task_runtime: Mock) -> None:
        runtime = Mock()
        load_task_runtime.return_value = runtime
        workspace = DebugWorkspace(Path("debug"))
        session = AutomationSession(
            controller=Mock(),
            config=_config(),
            project_root=Path.cwd(),
            workspace=workspace,
        )

        first = session.initialize_runtime()
        second = session.initialize_runtime()

        self.assertIs(first, runtime)
        self.assertIs(second, runtime)
        load_task_runtime.assert_called_once_with(
            session.controller,
            (Path.cwd() / "assets/resource").resolve(),
            workspace.logs / "maa",
        )

    @patch("window_auto.application.session.deactivate_controller")
    def test_close_is_idempotent(self, deactivate_controller: Mock) -> None:
        session = AutomationSession(
            controller=Mock(),
            config=_config(),
            project_root=Path.cwd(),
            workspace=DebugWorkspace(Path("debug")),
        )

        session.close()
        session.close()

        deactivate_controller.assert_called_once_with(session.controller)
        self.assertTrue(session.closed)


if __name__ == "__main__":
    unittest.main()
