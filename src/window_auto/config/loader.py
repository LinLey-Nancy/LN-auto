"""Load and validate framework configuration."""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any


REQUIRED_TOP_LEVEL_KEYS = {"window", "controller", "runtime", "diagnostics"}

# Upper bound for any configured time value: one day in milliseconds. This
# keeps time.sleep()/threading.Timer() far away from platform overflow limits.
MAX_TIME_MS = 86_400_000


def _optional_positive_resolution(config: dict[str, Any], key: str) -> list[int] | None:
    value = config.get(key)
    if value is None:
        return None
    if not (
        isinstance(value, list)
        and len(value) == 2
        and all(
            not isinstance(component, bool)
            and isinstance(component, int)
            and component > 0
            for component in value
        )
    ):
        raise ValueError(f"controller.{key} must be null or two positive integers.")
    return value


_HUMANIZE_KEYS = {"enabled", "click_jitter_px", "timing_jitter_ratio", "mouse_curve"}


def _validate_humanize(humanize: Any) -> None:
    if humanize is None:
        return
    if not isinstance(humanize, dict):
        raise ValueError("controller.humanize must be an object.")
    unknown_keys = set(humanize).difference(_HUMANIZE_KEYS)
    if unknown_keys:
        names = ", ".join(sorted(unknown_keys))
        raise ValueError(f"controller.humanize has unknown keys: {names}")
    enabled = humanize.get("enabled", False)
    if not isinstance(enabled, bool):
        raise ValueError("controller.humanize.enabled must be a boolean.")
    click_jitter_px = humanize.get("click_jitter_px", 3)
    if (
        isinstance(click_jitter_px, bool)
        or not isinstance(click_jitter_px, int)
        or click_jitter_px < 0
    ):
        raise ValueError("controller.humanize.click_jitter_px must be a non-negative integer.")
    timing_jitter_ratio = humanize.get("timing_jitter_ratio", 0.4)
    if (
        isinstance(timing_jitter_ratio, bool)
        or not isinstance(timing_jitter_ratio, (int, float))
        or not 0 <= timing_jitter_ratio <= 0.9
    ):
        raise ValueError(
            "controller.humanize.timing_jitter_ratio must be a number between 0 and 0.9."
        )
    mouse_curve = humanize.get("mouse_curve", True)
    if not isinstance(mouse_curve, bool):
        raise ValueError("controller.humanize.mouse_curve must be a boolean.")


def load_config(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise FileNotFoundError(f"Configuration file does not exist: {path}")

    with path.open(encoding="utf-8") as file:
        config: dict[str, Any] = json.load(file)

    missing_keys = REQUIRED_TOP_LEVEL_KEYS.difference(config)
    if missing_keys:
        names = ", ".join(sorted(missing_keys))
        raise ValueError(f"Configuration is missing required sections: {names}")

    title_pattern = config["window"].get("title_pattern")
    if not isinstance(title_pattern, str):
        raise ValueError("window.title_pattern must be a string.")

    class_name = config["window"].get("class_name")
    if class_name is not None and not isinstance(class_name, str):
        raise ValueError("window.class_name must be a string or null.")

    screenshot_target_long_side = config["controller"].get("screenshot_target_long_side")
    if (
        isinstance(screenshot_target_long_side, bool)
        or not isinstance(screenshot_target_long_side, int)
        or screenshot_target_long_side <= 0
    ):
        raise ValueError("controller.screenshot_target_long_side must be a positive integer.")
    screencap_mode = config["controller"].get("screencap_mode")
    if screencap_mode not in {"background", "foreground"}:
        raise ValueError("controller.screencap_mode must be 'background' or 'foreground'.")
    for key in ("background_screencap", "foreground_screencap"):
        methods = config["controller"].get(key)
        if (
            not isinstance(methods, list)
            or not methods
            or any(not isinstance(method, str) or not method for method in methods)
        ):
            raise ValueError(f"controller.{key} must be a non-empty array of strings.")
    for key in ("mouse_input", "keyboard_input"):
        value = config["controller"].get(key)
        if not isinstance(value, str) or not value:
            raise ValueError(f"controller.{key} must be a non-empty string.")
    capture_scope = config["controller"].get("capture_scope", "window")
    if capture_scope not in {"window", "desktop"}:
        raise ValueError("controller.capture_scope must be 'window' or 'desktop'.")
    mouse_lock_follow = config["controller"].get("mouse_lock_follow", False)
    if not isinstance(mouse_lock_follow, bool):
        raise ValueError("controller.mouse_lock_follow must be a boolean.")
    direct_screen_input = config["controller"].get("direct_screen_input", False)
    if not isinstance(direct_screen_input, bool):
        raise ValueError("controller.direct_screen_input must be a boolean.")
    _optional_positive_resolution(config["controller"], "expected_raw_resolution")
    _optional_positive_resolution(config["controller"], "expected_screenshot_resolution")
    _validate_humanize(config["controller"].get("humanize"))

    debug_dir = config["diagnostics"].get("debug_dir")
    if not isinstance(debug_dir, str) or not debug_dir.strip():
        raise ValueError("diagnostics.debug_dir must be a non-empty string.")

    resource_path = config["runtime"].get("resource_path")
    if not isinstance(resource_path, str) or not resource_path.strip():
        raise ValueError("runtime.resource_path must be a non-empty string.")

    task_entry = config["runtime"].get("task_entry")
    if not isinstance(task_entry, str) or not task_entry.strip():
        raise ValueError("runtime.task_entry must be a non-empty string.")

    task_timeout_seconds = config["runtime"].get("task_timeout_seconds")
    if (
        isinstance(task_timeout_seconds, bool)
        or not isinstance(task_timeout_seconds, (int, float))
        or not math.isfinite(task_timeout_seconds)
        or task_timeout_seconds <= 0
    ):
        raise ValueError("runtime.task_timeout_seconds must be a positive finite number.")

    return config
