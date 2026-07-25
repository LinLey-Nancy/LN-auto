"""Terminal-independent window discovery and selection services."""

from __future__ import annotations

from dataclasses import dataclass

from nzm_auto.windowing.discovery import WindowInfo, find_windows
from nzm_auto.windowing.selector import WindowSelectionError, choose_window_by_index


@dataclass(frozen=True, slots=True)
class WindowQuery:
    """Filters used by both CLI and GUI window pickers."""

    title: str | None = None
    class_name: str | None = None
    visible_only: bool = False


def list_windows(query: WindowQuery | None = None) -> list[WindowInfo]:
    """Return matching windows without creating a controller or sending input."""
    query = query or WindowQuery()
    windows = find_windows(
        title_filter=query.title,
        class_filter=query.class_name,
    )
    windows = [window for window in windows if window.title.strip()]
    if query.visible_only:
        windows = [window for window in windows if window.visible]
    return windows


def choose_window(query: WindowQuery, index: int) -> WindowInfo:
    """Select one window by stable list index."""
    windows = list_windows(query)
    if not windows:
        raise WindowSelectionError("No candidate windows are available.")
    return choose_window_by_index(windows, index)
