"""Optional human-like variability for input timing, coordinates, and motion."""

from __future__ import annotations

from dataclasses import dataclass
import math
import random
from typing import Any


# SystemRandom draws from the OS entropy source, so jittered values cannot be
# predicted or reproduced from a seeded pseudo-random sequence.
_RANDOM = random.SystemRandom()

MAX_TIMING_JITTER_RATIO = 0.9


@dataclass(frozen=True, slots=True)
class HumanizeConfig:
    enabled: bool = False
    click_jitter_px: int = 0
    timing_jitter_ratio: float = 0.0
    mouse_curve: bool = False


def humanize_from_config(config: dict[str, Any]) -> HumanizeConfig:
    """Read ``controller.humanize`` tolerantly; anything invalid disables it."""
    controller = config.get("controller", {})
    if not isinstance(controller, dict):
        return HumanizeConfig()
    raw = controller.get("humanize", {})
    if not isinstance(raw, dict) or raw.get("enabled", False) is not True:
        return HumanizeConfig()
    jitter_px = raw.get("click_jitter_px", 3)
    if isinstance(jitter_px, bool) or not isinstance(jitter_px, int):
        jitter_px = 3
    ratio = raw.get("timing_jitter_ratio", 0.4)
    if isinstance(ratio, bool) or not isinstance(ratio, (int, float)):
        ratio = 0.4
    return HumanizeConfig(
        enabled=True,
        click_jitter_px=max(0, jitter_px),
        timing_jitter_ratio=min(MAX_TIMING_JITTER_RATIO, max(0.0, float(ratio))),
        mouse_curve=bool(raw.get("mouse_curve", True)),
    )


def uniform_seconds(min_seconds: float, max_seconds: float) -> float:
    return _RANDOM.uniform(min_seconds, max_seconds)


def jitter_point(point: tuple[int, int], radius_px: int) -> tuple[int, int]:
    """Offset ``point`` by a clamped Gaussian offset within ``radius_px``."""
    x, y = int(point[0]), int(point[1])
    if radius_px <= 0:
        return x, y
    # Gaussian falloff keeps most clicks near the intended point; the clamp
    # guarantees the offset never exceeds the configured radius.
    offset_x = int(round(_RANDOM.gauss(0.0, radius_px / 2.0)))
    offset_y = int(round(_RANDOM.gauss(0.0, radius_px / 2.0)))
    offset_x = max(-radius_px, min(radius_px, offset_x))
    offset_y = max(-radius_px, min(radius_px, offset_y))
    return max(0, x + offset_x), max(0, y + offset_y)


def jitter_duration_ms(base_ms: int, ratio: float) -> int:
    """Randomize ``base_ms`` uniformly within +/- ``ratio`` of itself."""
    base = max(0, int(base_ms))
    if base == 0 or ratio <= 0.0:
        return base
    ratio = min(MAX_TIMING_JITTER_RATIO, ratio)
    low = base * (1.0 - ratio)
    high = base * (1.0 + ratio)
    return max(1, int(round(_RANDOM.uniform(low, high))))


def curve_points(
    start: tuple[int, int],
    end: tuple[int, int],
    *,
    max_steps: int = 25,
) -> list[tuple[int, int]]:
    """Ease-in-out quadratic bezier from ``start`` to ``end``, ending exactly."""
    sx, sy = int(start[0]), int(start[1])
    ex, ey = int(end[0]), int(end[1])
    distance = math.hypot(ex - sx, ey - sy)
    if distance < 2.0:
        return [(ex, ey)]
    steps = max(2, min(max_steps, int(distance / 24)))
    # The control point is pushed perpendicular to the straight line so the
    # path arcs like a hand movement instead of sliding diagonally.
    normal_x, normal_y = -(ey - sy), (ex - sx)
    norm = math.hypot(normal_x, normal_y) or 1.0
    offset = _RANDOM.uniform(-0.3, 0.3) * distance
    control_x = (sx + ex) / 2 + normal_x / norm * offset
    control_y = (sy + ey) / 2 + normal_y / norm * offset
    points: list[tuple[int, int]] = []
    for index in range(1, steps + 1):
        t = index / steps
        # Smoothstep easing: slow at the ends, faster in the middle.
        t = t * t * (3.0 - 2.0 * t)
        inverse = 1.0 - t
        x = inverse * inverse * sx + 2 * inverse * t * control_x + t * t * ex
        y = inverse * inverse * sy + 2 * inverse * t * control_y + t * t * ey
        points.append((int(round(x)), int(round(y))))
    points[-1] = (ex, ey)
    return points
