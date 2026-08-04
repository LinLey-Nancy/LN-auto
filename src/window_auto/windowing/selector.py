"""Select one target window from read-only discovery results."""

from __future__ import annotations

from collections.abc import Sequence

from window_auto.windowing.discovery import WindowInfo, find_windows


class WindowSelectionError(RuntimeError):
    """Base error for deterministic target-window selection."""


class WindowNotFoundError(WindowSelectionError):
    """Raised when no window matches the configured filters."""


class AmbiguousWindowError(WindowSelectionError):
    """Raised when more than one window matches the configured filters."""


class WindowIndexError(WindowSelectionError):
    """Raised when an interactive selection index is invalid."""


def choose_window_by_index(windows: Sequence[WindowInfo], index: int) -> WindowInfo:
    if not windows:
        raise WindowNotFoundError("No candidate windows are available.")
    if index < 0 or index >= len(windows):
        raise WindowIndexError(
            f"Window index {index} is out of range; choose 0 through {len(windows) - 1}."
        )
    return windows[index]


def require_unique_window(
    windows: Sequence[WindowInfo],
    *,
    title_filter: str | None,
    class_filter: str | None,
) -> WindowInfo:
    description = f"title contains {title_filter!r}"
    if class_filter:
        description += f" and class contains {class_filter!r}"

    if not windows:
        raise WindowNotFoundError(f"No window matched: {description}.")
    if len(windows) > 1:
        matches = ", ".join(f"0x{window.hwnd:X} {window.title!r}" for window in windows)
        raise AmbiguousWindowError(
            f"Expected one window but found {len(windows)} for {description}: {matches}"
        )
    return windows[0]


def select_target_window(
    title_filter: str,
    class_filter: str | None = None,
) -> WindowInfo:
    if not title_filter.strip():
        raise WindowSelectionError("window.title_pattern must not be empty.")

    windows = find_windows(title_filter=title_filter, class_filter=class_filter)
    return require_unique_window(
        windows,
        title_filter=title_filter,
        class_filter=class_filter,
    )
