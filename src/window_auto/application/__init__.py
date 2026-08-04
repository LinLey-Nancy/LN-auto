"""Application services shared by the CLI and the future desktop GUI."""

from window_auto.application.session import AutomationSession
from window_auto.application.input_profiles import InputProfile, InputProfileName, get_input_profile
from window_auto.application.window_service import WindowQuery, choose_window, list_windows

__all__ = [
    "AutomationSession",
    "InputProfile",
    "InputProfileName",
    "WindowQuery",
    "choose_window",
    "get_input_profile",
    "list_windows",
]
