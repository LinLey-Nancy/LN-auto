from pathlib import Path
import json
import tempfile
import unittest
from unittest.mock import patch

import numpy

from window_auto.automation.template_action import (
    TemplateActionResult,
    TemplateNotFoundError,
)
from window_auto.automation.workflow import (
    WorkflowConfigError,
    WorkflowExecutionError,
    load_workflow,
    run_workflow,
)
from window_auto.diagnostics.input_test import VisualDifference
from window_auto.diagnostics.template_match import MatchBox
from window_auto.diagnostics.workspace import create_debug_workspace


def _write_workflow(root: Path, step_updates: dict | None = None) -> Path:
    template_path = root / "template.png"
    template_path.write_bytes(b"placeholder")
    step = {
        "name": "open-target",
        "template": str(template_path),
        "threshold": 0.9,
        "action": "double-click",
        "recognition_attempts": 2,
        "recognition_interval_ms": 0,
        "pre_delay_ms": 0,
        "post_delay_ms": 0,
        "require_visual_change": True,
    }
    if step_updates:
        step.update(step_updates)
    path = root / "workflow.json"
    path.write_text(
        json.dumps({"version": 1, "name": "test-workflow", "steps": [step]}),
        encoding="utf-8",
    )
    return path


def _action_result(root: Path, visual_change: bool = True) -> TemplateActionResult:
    difference = VisualDifference(1.0 if visual_change else 0.0, 0.1 if visual_change else 0.0, visual_change)
    return TemplateActionResult(
        action="double-click",
        point=(20, 30),
        click_count=2,
        score=0.95,
        box=MatchBox(10, 20, 20, 20),
        difference=difference,
        before_path=root / "before.png",
        after_path=root / "after.png",
        annotated_path=root / "target.png",
        difference_path=root / "difference.png",
        report_path=root / "step-report.json",
    )


class WorkflowTests(unittest.TestCase):
    def test_workflow_config_is_loaded(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            definition = load_workflow(_write_workflow(root), root)

        self.assertEqual(definition.name, "test-workflow")
        self.assertEqual(len(definition.steps), 1)
        self.assertEqual(definition.steps[0].recognition_attempts, 2)
        self.assertEqual(definition.steps[0].action, "double-click")

    def test_utf8_bom_workflow_is_loaded(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = _write_workflow(root)
            content = path.read_text(encoding="utf-8")
            path.write_text(content, encoding="utf-8-sig")

            definition = load_workflow(path, root)

        self.assertEqual(definition.name, "test-workflow")

    def test_unknown_step_field_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = _write_workflow(root, {"typo_field": True})
            with self.assertRaises(WorkflowConfigError):
                load_workflow(path, root)

    def test_missing_template_file_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = _write_workflow(root, {"template": "missing.png"})
            with self.assertRaises(WorkflowConfigError):
                load_workflow(path, root)

    def test_template_not_found_is_retried_before_input(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            definition = load_workflow(_write_workflow(root), root)
            workspace = create_debug_workspace(root, "debug")
            expected = _action_result(root)

            with (
                patch(
                    "window_auto.automation.workflow.load_template_image",
                    return_value=numpy.zeros((5, 5, 3), dtype=numpy.uint8),
                ),
                patch(
                    "window_auto.automation.workflow.run_template_action",
                    side_effect=[TemplateNotFoundError("not found"), expected],
                ) as action,
            ):
                result = run_workflow(definition, object(), object(), workspace)

        self.assertEqual(action.call_count, 2)
        self.assertEqual(result.steps[0].recognition_attempt, 2)

    def test_no_visual_change_stops_without_repeating_action(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            definition = load_workflow(_write_workflow(root), root)
            workspace = create_debug_workspace(root, "debug")
            expected = _action_result(root, visual_change=False)

            with (
                patch(
                    "window_auto.automation.workflow.load_template_image",
                    return_value=numpy.zeros((5, 5, 3), dtype=numpy.uint8),
                ),
                patch(
                    "window_auto.automation.workflow.run_template_action",
                    return_value=expected,
                ) as action,
            ):
                with self.assertRaises(WorkflowExecutionError):
                    run_workflow(definition, object(), object(), workspace)

        self.assertEqual(action.call_count, 1)
