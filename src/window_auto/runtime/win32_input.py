"""Precise foreground Win32 input for coordinate-sensitive application windows."""

from __future__ import annotations

import ctypes
from ctypes import wintypes
import sys
import time

from window_auto.windowing.discovery import WindowInfo


class DirectInputError(RuntimeError):
    """Raised when a guarded screen-coordinate input cannot be delivered safely."""


class _Rect(ctypes.Structure):
    _fields_ = (
        ("left", wintypes.LONG),
        ("top", wintypes.LONG),
        ("right", wintypes.LONG),
        ("bottom", wintypes.LONG),
    )


_BUTTON_FLAGS = {
    "left": (0x0002, 0x0004),
    "right": (0x0008, 0x0010),
    "middle": (0x0020, 0x0040),
}


def click_client_point(
    window: WindowInfo,
    point: tuple[int, int],
    button: str,
    *,
    hold_seconds: float = 0.03,
) -> tuple[int, int]:
    """Foreground ``window`` and click an exact client point in screen pixels."""
    if sys.platform != "win32":
        raise DirectInputError("前台精确输入仅支持 Windows 系统。")
    if button not in _BUTTON_FLAGS:
        raise DirectInputError(f"不支持的鼠标按键：{button!r}，请使用 left、right 或 middle。")

    user32 = ctypes.WinDLL("user32", use_last_error=True)
    hwnd = wintypes.HWND(window.hwnd)
    user32.IsWindow.argtypes = [wintypes.HWND]
    user32.IsWindow.restype = wintypes.BOOL
    user32.IsIconic.argtypes = [wintypes.HWND]
    user32.IsIconic.restype = wintypes.BOOL
    user32.ShowWindowAsync.argtypes = [wintypes.HWND, ctypes.c_int]
    user32.ShowWindowAsync.restype = wintypes.BOOL
    user32.BringWindowToTop.argtypes = [wintypes.HWND]
    user32.BringWindowToTop.restype = wintypes.BOOL
    user32.SetForegroundWindow.argtypes = [wintypes.HWND]
    user32.SetForegroundWindow.restype = wintypes.BOOL
    user32.GetForegroundWindow.restype = wintypes.HWND
    user32.GetClientRect.argtypes = [wintypes.HWND, ctypes.POINTER(_Rect)]
    user32.GetClientRect.restype = wintypes.BOOL
    user32.ClientToScreen.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.POINT)]
    user32.ClientToScreen.restype = wintypes.BOOL
    user32.SetCursorPos.argtypes = [ctypes.c_int, ctypes.c_int]
    user32.SetCursorPos.restype = wintypes.BOOL
    user32.GetCursorPos.argtypes = [ctypes.POINTER(wintypes.POINT)]
    user32.GetCursorPos.restype = wintypes.BOOL
    user32.mouse_event.argtypes = [
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.DWORD,
        ctypes.c_void_p,
    ]

    if not user32.IsWindow(hwnd):
        raise DirectInputError("目标窗口已关闭或不存在，未发送点击。请重新选择目标窗口后重试。")
    if user32.IsIconic(hwnd):
        user32.ShowWindowAsync(hwnd, 9)  # SW_RESTORE
        time.sleep(0.25)
    else:
        user32.ShowWindowAsync(hwnd, 5)  # SW_SHOW

    user32.BringWindowToTop(hwnd)
    user32.SetForegroundWindow(hwnd)
    for _ in range(10):
        if int(user32.GetForegroundWindow() or 0) == window.hwnd:
            break
        time.sleep(0.05)
        user32.BringWindowToTop(hwnd)
        user32.SetForegroundWindow(hwnd)
    else:
        raise DirectInputError(
            "Windows 不允许目标窗口切换到前台，未发送点击。"
            "请确认目标窗口未被全屏独占程序或远程桌面遮挡，然后重试。"
        )

    rect = _Rect()
    if not user32.GetClientRect(hwnd, ctypes.byref(rect)):
        raise DirectInputError(
            "无法读取目标窗口的客户区尺寸，未发送点击。请重新选择目标窗口后重试。"
        )
    width = max(0, rect.right - rect.left)
    height = max(0, rect.bottom - rect.top)
    x, y = point
    if not 0 <= x < width or not 0 <= y < height:
        raise DirectInputError(
            f"点击坐标 {point} 超出目标窗口当前客户区 {width}×{height}，未发送点击。"
            "可参考编辑器右下角的实时鼠标坐标重新取点，或调整窗口大小后重试。"
        )

    screen_point = wintypes.POINT(x, y)
    if not user32.ClientToScreen(hwnd, ctypes.byref(screen_point)):
        raise DirectInputError(
            "无法把点击坐标换算为屏幕坐标，未发送点击。请重新选择目标窗口后重试。"
        )
    if not user32.SetCursorPos(screen_point.x, screen_point.y):
        raise DirectInputError(
            "Windows 拒绝移动鼠标光标，未发送点击。"
            "通常是权限不足：目标程序可能以管理员身份运行，"
            "请尝试以管理员身份运行 LN-auto 后重试。"
        )
    time.sleep(0.03)

    actual = wintypes.POINT()
    if not user32.GetCursorPos(ctypes.byref(actual)):
        raise DirectInputError(
            "无法确认鼠标光标位置，未发送点击。请尝试以管理员身份运行 LN-auto 后重试。"
        )
    if (actual.x, actual.y) != (screen_point.x, screen_point.y):
        raise DirectInputError(
            "目标程序移动或锁定了鼠标光标，未发送点击。"
            "请退出目标程序的光标锁定（鼠标独占）模式，或改用其他输入策略后重试。"
        )

    down_flag, up_flag = _BUTTON_FLAGS[button]
    user32.mouse_event(down_flag, 0, 0, 0, None)
    time.sleep(max(0.0, hold_seconds))
    user32.mouse_event(up_flag, 0, 0, 0, None)
    return int(screen_point.x), int(screen_point.y)
