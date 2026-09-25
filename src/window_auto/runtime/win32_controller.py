"""Create and connect a MaaFramework Win32 controller."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from maa.controller import Win32Controller
from maa.define import MaaWin32InputMethodEnum, MaaWin32ScreencapMethodEnum

from window_auto.windowing.discovery import WindowInfo


class ControllerConnectionError(RuntimeError):
    """Raised when a Win32 controller cannot be configured or connected."""


def combine_screencap_methods(method_names: Sequence[str]) -> int:
    if not method_names:
        raise ControllerConnectionError("At least one screenshot method must be configured.")

    combined = 0
    for method_name in method_names:
        try:
            combined |= int(MaaWin32ScreencapMethodEnum[method_name])
        except KeyError as error:
            raise ControllerConnectionError(
                f"Unknown Win32 screenshot method: {method_name!r}."
            ) from error
    return combined


def parse_input_method(method_name: str) -> int:
    try:
        return int(MaaWin32InputMethodEnum[method_name])
    except KeyError as error:
        raise ControllerConnectionError(
            f"Unknown Win32 input method: {method_name!r}."
        ) from error


def create_controller(window: WindowInfo, controller_config: dict[str, Any]) -> Win32Controller:
    try:
        screencap_mode = controller_config["screencap_mode"]
        screencap_methods = (
            controller_config["background_screencap"]
            if screencap_mode == "background"
            else controller_config["foreground_screencap"]
        )
        mouse_input = controller_config["mouse_input"]
        keyboard_input = controller_config["keyboard_input"]
        target_long_side = controller_config["screenshot_target_long_side"]
    except KeyError as error:
        raise ControllerConnectionError(
            f"Controller configuration is missing the key: {error}"
        ) from error
    if screencap_mode not in {"background", "foreground"}:
        raise ControllerConnectionError(
            f"controller.screencap_mode must be 'background' or 'foreground', "
            f"got {screencap_mode!r}."
        )
    try:
        controller = Win32Controller(
            window.hwnd,
            combine_screencap_methods(screencap_methods),
            parse_input_method(mouse_input),
            parse_input_method(keyboard_input),
        )
    except ControllerConnectionError:
        raise
    except RuntimeError as error:
        raise ControllerConnectionError(
            f"Failed to create the Win32 controller: {error}"
        ) from error
    if not controller.set_screenshot_target_long_side(target_long_side):
        raise ControllerConnectionError(
            f"Failed to set Maa screenshot target long side to {target_long_side}."
        )
    return controller


def connect_controller(
    controller: Win32Controller,
    controller_config: dict[str, Any],
) -> tuple[tuple[int, int], tuple[int, int]]:
    job = controller.post_connection().wait()
    if not job.succeeded or not controller.connected:
        raise ControllerConnectionError("MaaFramework failed to connect the Win32 controller.")
    if controller_config.get("mouse_lock_follow", False):
        if controller_config["mouse_input"] not in {"PostMessage", "SendMessage"}:
            raise ControllerConnectionError(
                "Mouse-lock following requires a message-based Win32 mouse input method."
            )
        if not controller.set_mouse_lock_follow(True):
            raise ControllerConnectionError(
                "Failed to enable Maa mouse-lock following for the target window."
            )

    screenshot_job = controller.post_screencap().wait()
    if not screenshot_job.succeeded:
        raise ControllerConnectionError(
            "MaaFramework connected but failed the startup screenshot check."
        )
    screenshot = screenshot_job.get()
    raw_resolution = tuple(controller.resolution)
    if raw_resolution[0] <= 0 or raw_resolution[1] <= 0:
        raise ControllerConnectionError(
            f"Invalid raw controller resolution {raw_resolution!r}; no input was sent."
        )

    screenshot_height, screenshot_width = screenshot.shape[:2]
    screenshot_resolution = (screenshot_width, screenshot_height)
    if screenshot_width <= 0 or screenshot_height <= 0:
        raise ControllerConnectionError(
            f"Invalid screenshot resolution {screenshot_resolution!r}; no input was sent."
        )

    if controller_config.get("capture_scope", "window") == "window":
        expected_raw = controller_config.get("expected_raw_resolution")
        if expected_raw is not None and raw_resolution != tuple(expected_raw):
            raise ControllerConnectionError(
                f"Raw resolution {raw_resolution[0]}x{raw_resolution[1]} does not match "
                f"required {expected_raw[0]}x{expected_raw[1]}; no input was sent."
            )
        expected_screenshot = controller_config.get("expected_screenshot_resolution")
        if expected_screenshot is not None and screenshot_resolution != tuple(expected_screenshot):
            raise ControllerConnectionError(
                f"Screenshot resolution {screenshot_width}x{screenshot_height} does not match "
                f"required {expected_screenshot[0]}x{expected_screenshot[1]}; no input was sent."
            )

    target_long_side = controller_config["screenshot_target_long_side"]
    if abs(max(screenshot_resolution) - target_long_side) > 1:
        raise ControllerConnectionError(
            f"Screenshot resolution {screenshot_width}x{screenshot_height} does not match "
            f"target long side {target_long_side}; no input was sent."
        )
    return raw_resolution, screenshot_resolution


def deactivate_controller(controller: Win32Controller) -> None:
    job = controller.post_inactive().wait()
    if not job.succeeded:
        raise ControllerConnectionError("MaaFramework failed to deactivate the Win32 controller.")
