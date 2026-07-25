"""Enumerate desktop windows without creating a controller."""

from __future__ import annotations

import ctypes
from ctypes import wintypes
from dataclasses import asdict, dataclass
import sys
from typing import Any


@dataclass(frozen=True, slots=True)
class WindowInfo:
    hwnd: int
    title: str
    class_name: str
    window_width: int | None
    window_height: int | None
    client_width: int | None
    client_height: int | None
    visible: bool
    minimized: bool
    client_x: int | None = None
    client_y: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class _Rect(ctypes.Structure):
    _fields_ = (
        ("left", wintypes.LONG),
        ("top", wintypes.LONG),
        ("right", wintypes.LONG),
        ("bottom", wintypes.LONG),
    )


def _handle_value(handle: Any) -> int:
    value = getattr(handle, "value", handle)
    if value is None:
        return 0
    return int(value)


def _rect_size(user32: Any, function_name: str, hwnd: int) -> tuple[int | None, int | None]:
    rect = _Rect()
    function = getattr(user32, function_name)
    if not function(wintypes.HWND(hwnd), ctypes.byref(rect)):
        return None, None
    return max(0, rect.right - rect.left), max(0, rect.bottom - rect.top)


def _client_origin(user32: Any, hwnd: int) -> tuple[int | None, int | None]:
    point = wintypes.POINT(0, 0)
    if not user32.ClientToScreen(wintypes.HWND(hwnd), ctypes.byref(point)):
        return None, None
    return int(point.x), int(point.y)


def matches_filters(
    window: WindowInfo,
    title_filter: str | None = None,
    class_filter: str | None = None,
) -> bool:
    if title_filter and title_filter.casefold() not in window.title.casefold():
        return False
    if class_filter and class_filter.casefold() not in window.class_name.casefold():
        return False
    return True


def find_windows(
    title_filter: str | None = None,
    class_filter: str | None = None,
) -> list[WindowInfo]:
    if sys.platform != "win32":
        raise RuntimeError("Desktop window discovery is only supported on Windows.")

    from maa.toolkit import Toolkit

    user32 = ctypes.WinDLL("user32", use_last_error=True)
    user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(_Rect)]
    user32.GetWindowRect.restype = wintypes.BOOL
    user32.GetClientRect.argtypes = [wintypes.HWND, ctypes.POINTER(_Rect)]
    user32.GetClientRect.restype = wintypes.BOOL
    user32.IsWindowVisible.argtypes = [wintypes.HWND]
    user32.IsWindowVisible.restype = wintypes.BOOL
    user32.IsIconic.argtypes = [wintypes.HWND]
    user32.IsIconic.restype = wintypes.BOOL
    user32.ClientToScreen.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.POINT)]
    user32.ClientToScreen.restype = wintypes.BOOL

    windows: list[WindowInfo] = []
    for desktop_window in Toolkit.find_desktop_windows():
        hwnd = _handle_value(desktop_window.hwnd)
        window_width, window_height = _rect_size(user32, "GetWindowRect", hwnd)
        client_width, client_height = _rect_size(user32, "GetClientRect", hwnd)
        client_x, client_y = _client_origin(user32, hwnd)
        info = WindowInfo(
            hwnd=hwnd,
            title=desktop_window.window_name,
            class_name=desktop_window.class_name,
            window_width=window_width,
            window_height=window_height,
            client_width=client_width,
            client_height=client_height,
            visible=bool(user32.IsWindowVisible(wintypes.HWND(hwnd))),
            minimized=bool(user32.IsIconic(wintypes.HWND(hwnd))),
            client_x=client_x,
            client_y=client_y,
        )
        if matches_filters(info, title_filter, class_filter):
            windows.append(info)

    return windows
