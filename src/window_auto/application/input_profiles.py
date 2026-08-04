"""Explicit Win32 input profiles and their compatibility trade-offs."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class InputProfileName(StrEnum):
    BACKGROUND_MESSAGE = "background-message"
    BACKGROUND_WINDOW_MESSAGE = "background-window-message"
    FOREGROUND_PRECISE = "foreground-precise"
    FOREGROUND_COMPATIBLE = "foreground-compatible"
    DRIVER_INTERCEPTION = "driver-interception"


@dataclass(frozen=True, slots=True)
class InputProfile:
    name: InputProfileName
    mouse_method: str
    keyboard_method: str
    supports_background: bool
    mouse_lock_follow: bool
    direct_screen_input: bool
    requires_admin: bool
    requires_external_driver: bool
    compatibility: str
    warning: str


INPUT_PROFILES = {
    InputProfileName.BACKGROUND_MESSAGE: InputProfile(
        name=InputProfileName.BACKGROUND_MESSAGE,
        mouse_method="PostMessage",
        keyboard_method="PostMessage",
        supports_background=True,
        mouse_lock_follow=False,
        direct_screen_input=False,
        requires_admin=False,
        requires_external_driver=False,
        compatibility="medium",
        warning=(
            "后台消息可能显示发送成功，但目标程序仍可能忽略模拟输入；"
            "请通过画面变化确认操作是否真正生效。"
        ),
    ),
    InputProfileName.BACKGROUND_WINDOW_MESSAGE: InputProfile(
        name=InputProfileName.BACKGROUND_WINDOW_MESSAGE,
        mouse_method="PostMessage",
        keyboard_method="PostMessage",
        supports_background=True,
        mouse_lock_follow=True,
        direct_screen_input=False,
        requires_admin=False,
        requires_external_driver=False,
        compatibility="high",
        warning=(
            "向选中的目标窗口发送后台消息，并启用 MaaFramework 鼠标锁定跟随；"
            "仅适用于已经确认接受后台消息的目标程序。"
        ),
    ),
    InputProfileName.FOREGROUND_PRECISE: InputProfile(
        name=InputProfileName.FOREGROUND_PRECISE,
        mouse_method="PostMessage",
        keyboard_method="Seize",
        supports_background=False,
        mouse_lock_follow=False,
        direct_screen_input=True,
        requires_admin=True,
        requires_external_driver=False,
        compatibility="high",
        warning=(
            "将恢复并置顶目标窗口，把客户区坐标直接换算为屏幕像素，"
            "并短暂占用物理鼠标。自动化程序权限必须与目标程序相同。"
        ),
    ),
    InputProfileName.FOREGROUND_COMPATIBLE: InputProfile(
        name=InputProfileName.FOREGROUND_COMPATIBLE,
        mouse_method="Seize",
        keyboard_method="Seize",
        supports_background=False,
        mouse_lock_follow=False,
        direct_screen_input=False,
        requires_admin=False,
        requires_external_driver=False,
        compatibility="high",
        warning=(
            "目标窗口必须位于前台，运行期间可能短暂占用物理鼠标和键盘。"
        ),
    ),
    InputProfileName.DRIVER_INTERCEPTION: InputProfile(
        name=InputProfileName.DRIVER_INTERCEPTION,
        mouse_method="Interception",
        keyboard_method="Interception",
        supports_background=False,
        mouse_lock_follow=False,
        direct_screen_input=False,
        requires_admin=True,
        requires_external_driver=True,
        compatibility="medium",
        warning=(
            "需要安装 Interception 驱动并使用管理员权限；驱动必须由用户主动安装。"
        ),
    ),
}


def get_input_profile(name: InputProfileName | str) -> InputProfile:
    try:
        return INPUT_PROFILES[InputProfileName(name)]
    except (KeyError, ValueError) as error:
        supported = ", ".join(profile.value for profile in InputProfileName)
        raise ValueError(f"Unknown input profile {name!r}; choose one of: {supported}.") from error
