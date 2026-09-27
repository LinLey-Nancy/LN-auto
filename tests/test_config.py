from pathlib import Path
import json
import tempfile
import unittest

from window_auto.config.loader import load_config


class DefaultConfigTests(unittest.TestCase):
    def test_default_config_loads(self) -> None:
        project_root = Path(__file__).resolve().parents[1]
        config = load_config(project_root / "config" / "default.json")

        self.assertEqual(config["runtime"]["task_entry"], "FrameworkSelfTest")
        self.assertEqual(config["runtime"]["task_timeout_seconds"], 60)
        self.assertEqual(config["controller"]["capture_scope"], "window")
        self.assertFalse(config["controller"]["mouse_lock_follow"])
        self.assertFalse(config["controller"]["direct_screen_input"])
        self.assertEqual(config["controller"]["expected_raw_resolution"], [1920, 1080])
        self.assertEqual(config["controller"]["expected_screenshot_resolution"], [1280, 720])

    def test_non_positive_task_timeout_is_rejected(self) -> None:
        project_root = Path(__file__).resolve().parents[1]
        default_path = project_root / "config" / "default.json"
        config = json.loads(default_path.read_text(encoding="utf-8"))
        config["runtime"]["task_timeout_seconds"] = 0

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.json"
            path.write_text(json.dumps(config), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "task_timeout_seconds"):
                load_config(path)

    def test_null_expected_resolutions_are_allowed(self) -> None:
        project_root = Path(__file__).resolve().parents[1]
        default_path = project_root / "config" / "default.json"
        config = json.loads(default_path.read_text(encoding="utf-8"))
        config["controller"]["expected_raw_resolution"] = None
        config["controller"]["expected_screenshot_resolution"] = None

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.json"
            path.write_text(json.dumps(config), encoding="utf-8")
            loaded = load_config(path)

        self.assertIsNone(loaded["controller"]["expected_raw_resolution"])
        self.assertIsNone(loaded["controller"]["expected_screenshot_resolution"])

    def test_invalid_capture_scope_is_rejected(self) -> None:
        project_root = Path(__file__).resolve().parents[1]
        default_path = project_root / "config" / "default.json"
        config = json.loads(default_path.read_text(encoding="utf-8"))
        config["controller"]["capture_scope"] = "monitor"

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.json"
            path.write_text(json.dumps(config), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "capture_scope"):
                load_config(path)

    def test_non_boolean_mouse_lock_follow_is_rejected(self) -> None:
        project_root = Path(__file__).resolve().parents[1]
        default_path = project_root / "config" / "default.json"
        config = json.loads(default_path.read_text(encoding="utf-8"))
        config["controller"]["mouse_lock_follow"] = "yes"

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.json"
            path.write_text(json.dumps(config), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "mouse_lock_follow"):
                load_config(path)

    def test_non_boolean_direct_screen_input_is_rejected(self) -> None:
        project_root = Path(__file__).resolve().parents[1]
        default_path = project_root / "config" / "default.json"
        config = json.loads(default_path.read_text(encoding="utf-8"))
        config["controller"]["direct_screen_input"] = 1

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.json"
            path.write_text(json.dumps(config), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "direct_screen_input"):
                load_config(path)

    def _write_modified_config(self, mutate) -> Path:
        project_root = Path(__file__).resolve().parents[1]
        default_path = project_root / "config" / "default.json"
        config = json.loads(default_path.read_text(encoding="utf-8"))
        mutate(config)
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        path = Path(directory.name) / "config.json"
        path.write_text(json.dumps(config), encoding="utf-8")
        return path

    def test_invalid_screencap_mode_is_rejected(self) -> None:
        path = self._write_modified_config(
            lambda config: config["controller"].__setitem__("screencap_mode", "backgroud")
        )
        with self.assertRaisesRegex(ValueError, "screencap_mode"):
            load_config(path)

    def test_missing_mouse_input_is_rejected(self) -> None:
        path = self._write_modified_config(
            lambda config: config["controller"].pop("mouse_input")
        )
        with self.assertRaisesRegex(ValueError, "mouse_input"):
            load_config(path)

    def test_missing_keyboard_input_is_rejected(self) -> None:
        path = self._write_modified_config(
            lambda config: config["controller"].pop("keyboard_input")
        )
        with self.assertRaisesRegex(ValueError, "keyboard_input"):
            load_config(path)

    def test_empty_background_screencap_is_rejected(self) -> None:
        path = self._write_modified_config(
            lambda config: config["controller"].__setitem__("background_screencap", [])
        )
        with self.assertRaisesRegex(ValueError, "background_screencap"):
            load_config(path)

    def test_non_finite_task_timeout_is_rejected(self) -> None:
        # json.dumps emits the bare token NaN, which json.loads accepts back.
        path = self._write_modified_config(
            lambda config: config["runtime"].__setitem__(
                "task_timeout_seconds", float("nan")
            )
        )
        with self.assertRaisesRegex(ValueError, "task_timeout_seconds"):
            load_config(path)


class HumanizeConfigTests(unittest.TestCase):
    def _write_modified_config(self, mutate) -> Path:
        project_root = Path(__file__).resolve().parents[1]
        default_path = project_root / "config" / "default.json"
        config = json.loads(default_path.read_text(encoding="utf-8"))
        mutate(config)
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        path = Path(directory.name) / "config.json"
        path.write_text(json.dumps(config), encoding="utf-8")
        return path

    def test_default_config_enables_humanize(self) -> None:
        project_root = Path(__file__).resolve().parents[1]
        config = load_config(project_root / "config" / "default.json")

        humanize = config["controller"]["humanize"]
        self.assertTrue(humanize["enabled"])
        self.assertGreater(humanize["click_jitter_px"], 0)
        self.assertGreater(humanize["timing_jitter_ratio"], 0)
        self.assertTrue(humanize["mouse_curve"])

    def test_missing_humanize_section_is_allowed(self) -> None:
        path = self._write_modified_config(
            lambda config: config["controller"].pop("humanize")
        )

        config = load_config(path)

        self.assertNotIn("humanize", config["controller"])

    def test_non_object_humanize_is_rejected(self) -> None:
        path = self._write_modified_config(
            lambda config: config["controller"].__setitem__("humanize", "yes")
        )
        with self.assertRaisesRegex(ValueError, "humanize"):
            load_config(path)

    def test_unknown_humanize_key_is_rejected(self) -> None:
        path = self._write_modified_config(
            lambda config: config["controller"]["humanize"].__setitem__("teleport", True)
        )
        with self.assertRaisesRegex(ValueError, "humanize"):
            load_config(path)

    def test_out_of_range_timing_jitter_ratio_is_rejected(self) -> None:
        path = self._write_modified_config(
            lambda config: config["controller"]["humanize"].__setitem__(
                "timing_jitter_ratio", 1.5
            )
        )
        with self.assertRaisesRegex(ValueError, "timing_jitter_ratio"):
            load_config(path)

    def test_negative_click_jitter_is_rejected(self) -> None:
        path = self._write_modified_config(
            lambda config: config["controller"]["humanize"].__setitem__(
                "click_jitter_px", -1
            )
        )
        with self.assertRaisesRegex(ValueError, "click_jitter_px"):
            load_config(path)


if __name__ == "__main__":
    unittest.main()
