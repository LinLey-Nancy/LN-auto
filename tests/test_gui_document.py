import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from window_auto.gui.document import WorkflowDocument
from window_auto.workflow.loader import WorkflowV2ConfigError, load_workflow_v2


class WorkflowDocumentTests(unittest.TestCase):
    def test_steps_can_be_added_moved_updated_and_removed(self) -> None:
        document = WorkflowDocument()

        wait_index = document.add_step("wait")
        click_index = document.add_step("mouse_click")
        document.update_step(wait_index, "name", "准备")
        moved = document.move_step(click_index, -1)

        self.assertEqual(moved, 0)
        self.assertEqual(document.steps[0]["type"], "mouse_click")
        self.assertEqual(document.steps[1]["name"], "准备")
        document.remove_step(0)
        self.assertEqual(len(document.steps), 1)
        self.assertTrue(document.dirty)

    def test_insert_step_places_step_at_position(self) -> None:
        document = WorkflowDocument()
        document.add_step("wait")
        document.add_step("wait")

        inserted = document.insert_step("mouse_click", 1)

        self.assertEqual(inserted, 1)
        self.assertEqual(
            [step["type"] for step in document.steps],
            ["wait", "mouse_click", "wait"],
        )
        ids = [step["id"] for step in document.steps]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertTrue(document.dirty)

    def test_insert_step_clamps_out_of_range_position(self) -> None:
        document = WorkflowDocument()
        document.add_step("wait")

        self.assertEqual(document.insert_step("wait", 99), 1)
        self.assertEqual(document.insert_step("wait", -5), 0)
        self.assertEqual(document.steps[0]["id"], "wait-3")

    def test_duplicate_step_id_is_rejected(self) -> None:
        document = WorkflowDocument()
        first = document.add_step("wait")
        second = document.add_step("wait")
        document.update_step(first, "id", "same")

        with self.assertRaises(ValueError):
            document.update_step(second, "id", "same")

    def test_saved_document_round_trips_through_v2_validator(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "workflow.json"
            document = WorkflowDocument()
            document.set_name("GUI test")
            document.set_target("Test Window", None)
            document.add_step("wait")

            saved = document.save(path)
            loaded = WorkflowDocument.load(saved, root)

            self.assertEqual(loaded.name, "GUI test")
            self.assertEqual(loaded.steps[0]["type"], "wait")
            self.assertFalse(loaded.dirty)
            self.assertEqual(json.loads(path.read_text(encoding="utf-8"))["version"], 2)

    def test_unbound_target_round_trips_as_no_target(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "workflow.json"
            document = WorkflowDocument()
            document.add_step("wait")
            document.save(path)

            definition = load_workflow_v2(path, root)
            loaded = WorkflowDocument.load(path, root)

            self.assertIsNone(definition.target)
            self.assertEqual(loaded.data["target"]["title_pattern"], "")

    def test_random_delay_range_is_validated_during_editing(self) -> None:
        document = WorkflowDocument()
        index = document.add_step("wait")

        with self.assertRaisesRegex(ValueError, "最短延迟"):
            document.update_step(index, "min_duration_ms", 900)
        with self.assertRaisesRegex(ValueError, "最长延迟"):
            document.update_step(index, "max_duration_ms", 200)

    def test_save_with_project_root_rejects_unopenable_documents(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "workflow.json"
            document = WorkflowDocument()  # zero steps: loader requires a non-empty list
            document.set_name("未保存的草稿")

            with self.assertRaisesRegex(WorkflowV2ConfigError, "steps"):
                document.save(path, root)

            self.assertFalse(path.exists())
            self.assertTrue(document.dirty)

    def test_save_with_project_root_rejects_missing_template(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "workflow.json"
            document = WorkflowDocument()
            document.add_step("template_match")  # default template file does not exist

            with self.assertRaisesRegex(WorkflowV2ConfigError, "template"):
                document.save(path, root)

            self.assertFalse(path.exists())

    def test_save_with_project_root_keeps_valid_document_openable(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "workflow.json"
            document = WorkflowDocument()
            document.add_step("wait")

            saved = document.save(path, root)
            loaded = WorkflowDocument.load(saved, root)

            self.assertEqual(loaded.steps[0]["type"], "wait")
            self.assertFalse(loaded.dirty)

    def test_auto_delay_setting_round_trips_through_save(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "workflow.json"
            document = WorkflowDocument()
            document.add_step("wait")

            self.assertEqual(document.auto_delay["mode"], "none")
            document.set_auto_delay("random", fixed_ms=500, min_ms=100, max_ms=200)

            self.assertTrue(document.dirty)
            saved = document.save(path, root)
            raw = json.loads(saved.read_text(encoding="utf-8"))
            self.assertEqual(raw["settings"]["auto_delay"]["mode"], "random")
            self.assertEqual(raw["settings"]["auto_delay"]["min_ms"], 100)

            definition = load_workflow_v2(saved, root)
            self.assertEqual(definition.settings.auto_delay.mode, "random")
            self.assertEqual(definition.settings.auto_delay.max_ms, 200)

    def test_auto_delay_rejects_min_above_max(self) -> None:
        document = WorkflowDocument()

        with self.assertRaises(ValueError):
            document.set_auto_delay("random", fixed_ms=500, min_ms=900, max_ms=100)

    def test_failed_save_leaves_no_temp_files_behind(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "locked.json"
            document = WorkflowDocument()
            document.add_step("wait")

            with patch(
                "window_auto.gui.document.os.replace",
                side_effect=PermissionError("locked"),
            ):
                with self.assertRaises(PermissionError):
                    document.save(path, root)

            self.assertEqual(list(root.iterdir()), [])


if __name__ == "__main__":
    unittest.main()
