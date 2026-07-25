import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from nzm_auto.gui.document import WorkflowDocument
from nzm_auto.workflow.loader import load_workflow_v2


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


if __name__ == "__main__":
    unittest.main()
