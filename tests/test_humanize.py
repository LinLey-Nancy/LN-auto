import unittest

from window_auto.runtime.humanize import (
    HumanizeConfig,
    curve_points,
    humanize_from_config,
    jitter_duration_ms,
    jitter_point,
)


class HumanizeConfigTests(unittest.TestCase):
    def test_missing_section_is_disabled(self) -> None:
        self.assertEqual(humanize_from_config({}), HumanizeConfig())
        self.assertEqual(humanize_from_config({"controller": {}}), HumanizeConfig())

    def test_enabled_section_reads_values(self) -> None:
        config = humanize_from_config(
            {
                "controller": {
                    "humanize": {
                        "enabled": True,
                        "click_jitter_px": 5,
                        "timing_jitter_ratio": 0.25,
                        "mouse_curve": False,
                    }
                }
            }
        )

        self.assertTrue(config.enabled)
        self.assertEqual(config.click_jitter_px, 5)
        self.assertAlmostEqual(config.timing_jitter_ratio, 0.25)
        self.assertFalse(config.mouse_curve)

    def test_enabled_section_uses_defaults_for_missing_values(self) -> None:
        config = humanize_from_config({"controller": {"humanize": {"enabled": True}}})

        self.assertEqual(config.click_jitter_px, 3)
        self.assertAlmostEqual(config.timing_jitter_ratio, 0.4)
        self.assertTrue(config.mouse_curve)

    def test_invalid_values_fall_back_to_safe_defaults(self) -> None:
        config = humanize_from_config(
            {
                "controller": {
                    "humanize": {
                        "enabled": True,
                        "click_jitter_px": "many",
                        "timing_jitter_ratio": "lots",
                        "mouse_curve": True,
                    }
                }
            }
        )

        self.assertEqual(config.click_jitter_px, 3)
        self.assertAlmostEqual(config.timing_jitter_ratio, 0.4)

    def test_ratio_is_clamped_to_supported_range(self) -> None:
        config = humanize_from_config(
            {"controller": {"humanize": {"enabled": True, "timing_jitter_ratio": 5.0}}}
        )

        self.assertAlmostEqual(config.timing_jitter_ratio, 0.9)

    def test_not_a_dict_is_disabled(self) -> None:
        self.assertEqual(
            humanize_from_config({"controller": {"humanize": "yes"}}),
            HumanizeConfig(),
        )


class JitterPointTests(unittest.TestCase):
    def test_zero_radius_returns_point_unchanged(self) -> None:
        self.assertEqual(jitter_point((100, 50), 0), (100, 50))

    def test_jitter_stays_within_radius(self) -> None:
        for _ in range(200):
            x, y = jitter_point((500, 300), 4)
            self.assertLessEqual(abs(x - 500), 4)
            self.assertLessEqual(abs(y - 300), 4)

    def test_jitter_actually_varies(self) -> None:
        points = {jitter_point((500, 300), 4) for _ in range(50)}
        self.assertGreater(len(points), 1)

    def test_jitter_never_goes_negative(self) -> None:
        for _ in range(200):
            x, y = jitter_point((1, 0), 5)
            self.assertGreaterEqual(x, 0)
            self.assertGreaterEqual(y, 0)


class JitterDurationTests(unittest.TestCase):
    def test_zero_base_stays_zero(self) -> None:
        self.assertEqual(jitter_duration_ms(0, 0.5), 0)

    def test_zero_ratio_returns_base(self) -> None:
        self.assertEqual(jitter_duration_ms(120, 0.0), 120)

    def test_jittered_duration_stays_within_ratio_bounds(self) -> None:
        for _ in range(200):
            value = jitter_duration_ms(100, 0.4)
            self.assertGreaterEqual(value, 60)
            self.assertLessEqual(value, 140)

    def test_jittered_duration_is_at_least_one(self) -> None:
        for _ in range(50):
            self.assertGreaterEqual(jitter_duration_ms(1, 0.9), 1)


class CurvePointsTests(unittest.TestCase):
    def test_tiny_distance_jumps_straight_to_target(self) -> None:
        self.assertEqual(curve_points((10, 10), (11, 11)), [(11, 11)])

    def test_curve_ends_exactly_at_target(self) -> None:
        points = curve_points((0, 0), (640, 480))

        self.assertEqual(points[-1], (640, 480))
        self.assertGreater(len(points), 2)

    def test_curve_is_bounded_by_max_steps(self) -> None:
        points = curve_points((0, 0), (4000, 3000))

        self.assertLessEqual(len(points), 25)

    def test_curve_points_are_integers(self) -> None:
        for x, y in curve_points((3, 7), (321, 654)):
            self.assertIsInstance(x, int)
            self.assertIsInstance(y, int)


if __name__ == "__main__":
    unittest.main()
