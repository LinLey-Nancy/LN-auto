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


if __name__ == "__main__":
    unittest.main()
