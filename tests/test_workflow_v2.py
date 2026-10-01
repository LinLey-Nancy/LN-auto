import json
from pathlib import Path
from tempfile import TemporaryDirectory
import threading
import time
import unittest
from unittest.mock import Mock, patch

import numpy
from PIL import Image

from window_auto.diagnostics.desktop_scope import DesktopRecognitionFrame
from window_auto.diagnostics.ocr_match import OcrRecognitionResult
from window_auto.diagnostics.template_match import MatchBox, TemplateRecognitionResult
from window_auto.windowing.discovery import WindowInfo
from window_auto.workflow.actions import (
    ActionResult,
    TemplateNotFoundError,
    WorkflowActionError,
    execute_action,
)
from window_auto.workflow.context import CancellationToken, ExecutionContext
from window_auto.workflow.engine import WorkflowEngine, WorkflowExecutionError
from window_auto.workflow.events import WorkflowEventType
from window_auto.workflow.loader import WorkflowV2ConfigError, load_workflow_v2
from window_auto.workflow.model import (
    AutoDelay,
    KeyPressStep,
    MouseClickStep,
    MouseMoveStep,
    OcrMatchStep,
    RunWorkflowStep,
    TemplateMatchStep,
    TextInputStep,
    WaitStep,
    WorkflowDefinition,
    WorkflowSettings,
)
from window_auto.workflow.virtual_keys import resolve_text_character, resolve_virtual_key


class _Job:
    def __init__(self, succeeded: bool = True) -> None:
        self.succeeded = succeeded

    def wait(self):
        return self


class _Controller:
    def __init__(self) -> None:
        self.calls: list[tuple] = []
        self.fail_click = False
        self.resolution = (1920, 1080)

    def post_touch_move(self, x: int, y: int):
        self.calls.append(("move", x, y))
        return _Job()

    def post_relative_move(self, delta_x: int, delta_y: int):
        self.calls.append(("relative_move", delta_x, delta_y))
        return _Job()

    def post_click(self, x: int, y: int, contact: int = 0):
        self.calls.append(("click", x, y, contact))
        return _Job(not self.fail_click)

    def post_key_down(self, key: int):
        self.calls.append(("key_down", key))
        return _Job()

    def post_click_key(self, key: int):
        self.calls.append(("key", key))
        return _Job()

    def post_key_up(self, key: int):
        self.calls.append(("key_up", key))
        return _Job()

    def post_input_text(self, text: str):
        self.calls.append(("text", text))
        return _Job()

    def post_scroll(self, dx: int, dy: int):
        self.calls.append(("scroll", dx, dy))
        return _Job()


class _Session:
    def __init__(self) -> None:
        self.controller = _Controller()

    def initialize_runtime(self):
        return object()


def _context() -> tuple[_Session, ExecutionContext]:
    session = _Session()
    return session, ExecutionContext(session=session, cancellation=CancellationToken())


class WorkflowV2LoaderTests(unittest.TestCase):
    def test_complete_input_workflow_is_loaded(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            template = root / "template.png"
            Image.new("RGB", (4, 4)).save(template)
            data = {
                "version": 2,
                "name": "GUI workflow",
                "target": {"title_pattern": "示例应用", "class_name": "ExampleWindowClass"},
                "settings": {"stop_on_error": True, "default_timeout_ms": 5000},
                "steps": [
                    {
                        "id": "find",
                        "type": "template_match",
                        "name": "Find document",
                        "template": "template.png",
                        "result_variable": "document",
                    },
                    {
                        "id": "click",
                        "type": "mouse_click",
                        "name": "Open document",
                        "match_variable": "document",
                        "count": 2,
                    },
                    {
                        "id": "type",
                        "type": "text_input",
                        "name": "Type text",
                        "text": "Window automation test",
                    },
                ],
            }
            path = root / "workflow.json"
            path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

            definition = load_workflow_v2(path, root)

            self.assertEqual(definition.name, "GUI workflow")
            self.assertEqual(definition.target.title_pattern, "示例应用")
            self.assertEqual(len(definition.steps), 3)
            self.assertEqual(definition.steps[0].template_path, template.resolve())
            self.assertEqual(definition.steps[1].match_variable, "document")

    def test_click_requires_coordinates_or_match(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "workflow.json"
            path.write_text(
                json.dumps(
                    {
                        "version": 2,
                        "name": "invalid",
                        "steps": [
                            {
                                "id": "click",
                                "type": "mouse_click",
                                "name": "click",
                                "x": 1,
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )

            with self.assertRaises(WorkflowV2ConfigError):
                load_workflow_v2(path, root)

    def test_scroll_action_is_loaded_with_defaults(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "workflow.json"
            path.write_text(
                json.dumps(
                    {
                        "version": 2,
                        "name": "scroll",
                        "steps": [
                            {
                                "id": "scroll",
                                "type": "mouse_click",
                                "name": "scroll down",
                                "action": "scroll",
                                "x": 10,
                                "y": 20,
                                "scroll_direction": "down",
                                "scroll_amount": 5,
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )

            definition = load_workflow_v2(path, root)

            step = definition.steps[0]
            self.assertEqual(step.action, "scroll")
            self.assertEqual(step.scroll_direction, "down")
            self.assertEqual(step.scroll_amount, 5)

    def test_scroll_action_rejects_invalid_values(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            for field, value in (
                ("action", "drag"),
                ("scroll_direction", "left"),
            ):
                path = root / "workflow.json"
                path.write_text(
                    json.dumps(
                        {
                            "version": 2,
                            "name": "invalid",
                            "steps": [
                                {
                                    "id": "scroll",
                                    "type": "mouse_click",
                                    "name": "scroll",
                                    "action": "scroll",
                                    "x": 10,
                                    "y": 20,
                                    field: value,
                                }
                            ],
                        }
                    ),
                    encoding="utf-8",
                )

                with self.assertRaises(WorkflowV2ConfigError):
                    load_workflow_v2(path, root)

    def test_template_match_accepts_retry_failure_policy(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            Image.new("RGB", (4, 4)).save(root / "template.png")
            path = root / "workflow.json"
            path.write_text(
                json.dumps(
                    {
                        "version": 2,
                        "name": "retry recognition",
                        "steps": [
                            {
                                "id": "find",
                                "type": "template_match",
                                "name": "Find",
                                "on_failure": "retry",
                                "template": "template.png",
                                "result_variable": "match",
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )

            definition = load_workflow_v2(path, root)

            self.assertEqual(definition.steps[0].on_failure, "retry")

    def test_extended_action_parameters_are_loaded(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            Image.new("RGB", (4, 4)).save(root / "template.png")
            path = root / "workflow.json"
            path.write_text(
                json.dumps(
                    {
                        "version": 2,
                        "name": "extended",
                        "steps": [
                            {
                                "id": "find",
                                "type": "template_match",
                                "name": "Find",
                                "template": "template.png",
                                "result_variable": "match",
                                "post_action": "key_press",
                                "post_key": "F1",
                                "post_modifiers": ["CTRL"],
                                "post_key_hold_ms": 120,
                            },
                            {
                                "id": "delay",
                                "type": "wait",
                                "name": "Delay",
                                "delay_mode": "random",
                                "min_duration_ms": 100,
                                "max_duration_ms": 300,
                            },
                            {
                                "id": "move",
                                "type": "mouse_move",
                                "name": "Move",
                                "move_mode": "relative",
                                "delta_x": -20,
                                "delta_y": 40,
                            },
                            {
                                "id": "key",
                                "type": "key_press",
                                "name": "Key",
                                "key": "A",
                                "hold_ms": 250,
                            },
                        ],
                    }
                ),
                encoding="utf-8",
            )

            definition = load_workflow_v2(path, root)

            self.assertEqual(definition.steps[0].post_action, "key_press")
            self.assertEqual(definition.steps[0].post_key_hold_ms, 120)
            self.assertEqual(definition.steps[1].delay_mode, "random")
            self.assertEqual(definition.steps[1].max_duration_ms, 300)
            self.assertEqual(definition.steps[2].delta_x, -20)
            self.assertEqual(definition.steps[3].hold_ms, 250)

    def test_random_delay_range_must_be_ordered(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "workflow.json"
            path.write_text(
                json.dumps(
                    {
                        "version": 2,
                        "name": "invalid delay",
                        "steps": [
                            {
                                "id": "delay",
                                "type": "wait",
                                "name": "Delay",
                                "delay_mode": "random",
                                "min_duration_ms": 500,
                                "max_duration_ms": 100,
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )

            with self.assertRaises(WorkflowV2ConfigError):
                load_workflow_v2(path, root)

    def test_huge_time_values_are_rejected(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "workflow.json"
            path.write_text(
                json.dumps(
                    {
                        "version": 2,
                        "name": "huge",
                        "settings": {"default_timeout_ms": 9007199254740993},
                        "steps": [
                            {"id": "w", "type": "wait", "name": "W", "duration_ms": 10}
                        ],
                    }
                ),
                encoding="utf-8",
            )

            with self.assertRaisesRegex(WorkflowV2ConfigError, "default_timeout_ms"):
                load_workflow_v2(path, root)

    def test_out_of_range_virtual_key_codes_are_rejected(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "workflow.json"
            path.write_text(
                json.dumps(
                    {
                        "version": 2,
                        "name": "bad-key",
                        "steps": [
                            {
                                "id": "k",
                                "type": "key_press",
                                "name": "K",
                                "key": 300,
                                "modifiers": ["CTRL", 999],
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )

            with self.assertRaisesRegex(WorkflowV2ConfigError, "virtual key"):
                load_workflow_v2(path, root)

    def _write_ocr_workflow(self, root: Path, step: dict) -> Path:
        path = root / "workflow.json"
        path.write_text(
            json.dumps(
                {"version": 2, "name": "ocr", "steps": [step]},
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        return path

    def test_ocr_match_step_is_loaded(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            path = self._write_ocr_workflow(
                root,
                {
                    "id": "find",
                    "type": "ocr_match",
                    "name": "Find confirm",
                    "expected": ["确定", " OK "],
                    "threshold": 0.5,
                    "attempts": 2,
                    "interval_ms": 300,
                    "result_variable": "match",
                    "post_action": "click",
                    "post_button": "right",
                },
            )

            definition = load_workflow_v2(path, root)

            step = definition.steps[0]
            self.assertIsInstance(step, OcrMatchStep)
            self.assertEqual(step.expected, ("确定", "OK"))
            self.assertEqual(step.threshold, 0.5)
            self.assertEqual(step.attempts, 2)
            self.assertEqual(step.post_action, "click")
            self.assertEqual(step.post_button, "right")

    def test_ocr_match_rejects_empty_or_non_string_expected(self) -> None:
        for expected in ([], ["确定", ""], ["确定", 1], "确定"):
            with self.subTest(expected=expected), TemporaryDirectory() as directory:
                root = Path(directory)
                path = self._write_ocr_workflow(
                    root,
                    {
                        "id": "find",
                        "type": "ocr_match",
                        "name": "Find",
                        "expected": expected,
                        "result_variable": "match",
                    },
                )

                with self.assertRaisesRegex(WorkflowV2ConfigError, "expected"):
                    load_workflow_v2(path, root)

    def test_ocr_match_rejects_unknown_fields(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            path = self._write_ocr_workflow(
                root,
                {
                    "id": "find",
                    "type": "ocr_match",
                    "name": "Find",
                    "expected": ["确定"],
                    "result_variable": "match",
                    "template": "template.png",
                },
            )

            with self.assertRaisesRegex(WorkflowV2ConfigError, "Unknown"):
                load_workflow_v2(path, root)

    def test_ocr_match_accepts_retry_failure_policy(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            path = self._write_ocr_workflow(
                root,
                {
                    "id": "find",
                    "type": "ocr_match",
                    "name": "Find",
                    "on_failure": "retry",
                    "expected": ["确定"],
                    "result_variable": "match",
                },
            )

            definition = load_workflow_v2(path, root)

            self.assertEqual(definition.steps[0].on_failure, "retry")


class WorkflowV2ActionTests(unittest.TestCase):
    def test_mouse_and_keyboard_actions_use_maa_controller(self) -> None:
        session, context = _context()
        steps = (
            MouseMoveStep(id="move", name="Move", x=10, y=20),
            MouseClickStep(
                id="right-click",
                name="Right click",
                x=30,
                y=40,
                button="right",
            ),
            KeyPressStep(id="shortcut", name="Select all", key="A", modifiers=("CTRL",)),
            TextInputStep(id="text", name="Type", text="hello", strategy="direct"),
        )

        for step in steps:
            execute_action(step, context)

        self.assertEqual(
            session.controller.calls,
            [
                ("move", 10, 20),
                ("click", 30, 40, 1),
                ("key_down", 0x11),
                ("key_down", ord("A")),
                ("key_up", ord("A")),
                ("key_up", 0x11),
                ("text", "hello"),
            ],
        )

    def test_failed_controller_job_is_not_treated_as_success(self) -> None:
        session, context = _context()
        session.controller.fail_click = True

        with self.assertRaises(WorkflowActionError):
            execute_action(
                MouseClickStep(id="click", name="Click", x=1, y=2),
                context,
            )

    def test_virtual_key_names_and_codes_are_validated(self) -> None:
        self.assertEqual(resolve_virtual_key("enter"), 0x0D)
        self.assertEqual(resolve_virtual_key("F12"), 0x7B)
        self.assertEqual(resolve_virtual_key(0x41), 0x41)
        with self.assertRaises(ValueError):
            resolve_virtual_key("not-a-key")

    def test_key_sequence_resolves_case_and_punctuation(self) -> None:
        self.assertEqual(resolve_text_character("a"), (ord("A"), False))
        self.assertEqual(resolve_text_character("A"), (ord("A"), True))
        self.assertEqual(resolve_text_character("!"), (ord("1"), True))
        with self.assertRaises(ValueError):
            resolve_text_character("中")

    def test_key_sequence_text_uses_shift_and_character_delay(self) -> None:
        session, context = _context()

        execute_action(
            TextInputStep(
                id="text",
                name="Type",
                text="A!",
                strategy="key_sequence",
                interval_ms=0,
            ),
            context,
        )

        self.assertEqual(
            session.controller.calls,
            [
                ("key_down", 0x10),
                ("key_down", ord("A")),
                ("key_up", ord("A")),
                ("key_up", 0x10),
                ("key_down", 0x10),
                ("key_down", ord("1")),
                ("key_up", ord("1")),
                ("key_up", 0x10),
            ],
        )

    def test_precise_foreground_click_bypasses_controller_coordinate_mapping(self) -> None:
        session, context = _context()
        session.config = {"controller": {"direct_screen_input": True}}
        session.window = WindowInfo(
            hwnd=123,
            title="Application",
            class_name="UnrealWindow",
            window_width=1920,
            window_height=1080,
            client_width=1920,
            client_height=1080,
            visible=True,
            minimized=False,
        )

        with patch("window_auto.workflow.actions.click_client_point") as direct_click:
            execute_action(
                MouseClickStep(
                    id="precise-click",
                    name="Precise click",
                    x=1711,
                    y=949,
                    button="left",
                ),
                context,
            )

        direct_click.assert_called_once_with(session.window, (1711, 949), "left")
        self.assertEqual(session.controller.calls, [])

    def test_scroll_down_moves_pointer_then_scrolls(self) -> None:
        session, context = _context()

        result = execute_action(
            MouseClickStep(
                id="scroll",
                name="Scroll",
                action="scroll",
                x=100,
                y=200,
                scroll_direction="down",
                scroll_amount=3,
            ),
            context,
        )

        self.assertEqual(
            session.controller.calls,
            [("move", 100, 200), ("scroll", 0, -360)],
        )
        self.assertEqual(result.output["action"], "scroll")
        self.assertEqual(result.output["direction"], "down")
        self.assertEqual(result.output["amount"], 3)

    def test_scroll_up_uses_positive_wheel_delta(self) -> None:
        session, context = _context()

        execute_action(
            MouseClickStep(
                id="scroll",
                name="Scroll",
                action="scroll",
                x=1,
                y=2,
                scroll_direction="up",
                scroll_amount=5,
            ),
            context,
        )

        self.assertIn(("scroll", 0, 600), session.controller.calls)

    def test_scroll_can_target_recognized_match_center(self) -> None:
        session, context = _context()
        context.variables["match"] = MatchBox(100, 100, 40, 20)

        execute_action(
            MouseClickStep(
                id="scroll",
                name="Scroll",
                action="scroll",
                match_variable="match",
                scroll_direction="up",
                scroll_amount=1,
            ),
            context,
        )

        self.assertEqual(
            session.controller.calls,
            [("move", 120, 110), ("scroll", 0, 120)],
        )

    def test_precise_foreground_scroll_uses_direct_screen_input(self) -> None:
        session, context = _context()
        session.config = {"controller": {"direct_screen_input": True}}
        session.window = WindowInfo(
            hwnd=123,
            title="Application",
            class_name="UnrealWindow",
            window_width=1920,
            window_height=1080,
            client_width=1920,
            client_height=1080,
            visible=True,
            minimized=False,
        )

        with patch("window_auto.workflow.actions.scroll_client_point") as direct_scroll:
            execute_action(
                MouseClickStep(
                    id="scroll",
                    name="Scroll",
                    action="scroll",
                    x=300,
                    y=400,
                    scroll_direction="down",
                    scroll_amount=2,
                ),
                context,
            )

        direct_scroll.assert_called_once_with(session.window, (300, 400), -2)
        self.assertEqual(session.controller.calls, [])

    def test_relative_mouse_move_uses_controller_relative_move(self) -> None:
        session, context = _context()

        result = execute_action(
            MouseMoveStep(
                id="move",
                name="Move",
                move_mode="relative",
                delta_x=-30,
                delta_y=45,
            ),
            context,
        )

        self.assertEqual(session.controller.calls, [("relative_move", -30, 45)])
        self.assertEqual(result.output["delta"], (-30, 45))

    def test_key_press_holds_before_key_up(self) -> None:
        session = _Session()
        cancellation = Mock()
        context = ExecutionContext(session=session, cancellation=cancellation)

        execute_action(
            KeyPressStep(
                id="key",
                name="Key",
                key="A",
                hold_ms=125,
            ),
            context,
        )

        cancellation.wait.assert_called_once_with(0.125)
        self.assertEqual(
            session.controller.calls,
            [("key_down", ord("A")), ("key_up", ord("A"))],
        )

    def test_random_delay_uses_value_inside_configured_range(self) -> None:
        session = _Session()
        cancellation = Mock()
        context = ExecutionContext(session=session, cancellation=cancellation)
        with patch(
            "window_auto.workflow.actions._WAIT_RANDOM.randint", return_value=275
        ) as random_value:
            result = execute_action(
                WaitStep(
                    id="delay",
                    name="Delay",
                    delay_mode="random",
                    min_duration_ms=200,
                    max_duration_ms=400,
                ),
                context,
            )

        random_value.assert_called_once_with(200, 400)
        cancellation.wait.assert_called_once_with(0.275)
        self.assertEqual(result.output["duration_ms"], 275)

    def test_template_match_can_double_click_recognized_center(self) -> None:
        session, context = _context()
        recognition = TemplateRecognitionResult(
            hit=True,
            score=0.91,
            box=MatchBox(10, 20, 30, 40),
        )
        with (
            patch("window_auto.workflow.actions.load_template_image"),
            patch(
                "window_auto.workflow.actions.capture_image",
                return_value=numpy.zeros((720, 1280, 3), dtype=numpy.uint8),
            ),
            patch(
                "window_auto.workflow.actions.recognize_template",
                return_value=recognition,
            ),
        ):
            result = execute_action(
                TemplateMatchStep(
                    id="find",
                    name="Find",
                    template_path=Path("template.png"),
                    result_variable="match",
                    post_action="double_click",
                    post_button="right",
                    post_action_interval_ms=0,
                ),
                context,
            )

        self.assertEqual(
            session.controller.calls,
            [
                ("click", 38, 60, 1),
                ("click", 38, 60, 1),
            ],
        )
        self.assertEqual(result.output["post_action"]["action"], "double_click")

    def test_mouse_click_match_variable_uses_recognition_center(self) -> None:
        session, context = _context()
        context.variables["document"] = MatchBox(10, 20, 30, 40)

        result = execute_action(
            MouseClickStep(
                id="open",
                name="Open",
                match_variable="document",
                button="left",
            ),
            context,
        )

        self.assertEqual(session.controller.calls, [("click", 25, 40, 0)])
        self.assertEqual(result.output["point"], (25, 40))

    def test_template_result_variable_uses_raw_input_coordinates(self) -> None:
        session, context = _context()
        recognition = TemplateRecognitionResult(
            hit=True,
            score=0.9,
            box=MatchBox(10, 20, 30, 40),
        )
        with (
            patch("window_auto.workflow.actions.load_template_image"),
            patch(
                "window_auto.workflow.actions.capture_image",
                return_value=numpy.zeros((720, 1280, 3), dtype=numpy.uint8),
            ),
            patch(
                "window_auto.workflow.actions.recognize_template",
                return_value=recognition,
            ),
        ):
            execute_action(
                TemplateMatchStep(
                    id="find",
                    name="Find",
                    template_path=Path("template.png"),
                    result_variable="document",
                ),
                context,
            )
        result = execute_action(
            MouseClickStep(
                id="open",
                name="Open",
                match_variable="document",
            ),
            context,
        )

        self.assertEqual(session.controller.calls, [("click", 38, 60, 0)])
        self.assertEqual(result.output["point"], (38, 60))

    def test_desktop_scope_maps_match_into_target_window(self) -> None:
        session, context = _context()
        session.config = {
            "controller": {
                "capture_scope": "desktop",
                "screenshot_target_long_side": 1280,
            }
        }
        session.window = WindowInfo(
            hwnd=1,
            title="Target",
            class_name="TargetClass",
            window_width=800,
            window_height=600,
            client_width=800,
            client_height=600,
            visible=True,
            minimized=False,
            client_x=100,
            client_y=100,
        )
        session.controller_raw_size = (800, 600)
        session.controller_image_size = (1280, 960)
        frame = DesktopRecognitionFrame(
            image=numpy.zeros((720, 1280, 3), dtype=numpy.uint8),
            raw_size=(1920, 1080),
            recognition_size=(1280, 720),
        )
        recognition = TemplateRecognitionResult(
            hit=True,
            score=0.99,
            box=MatchBox(195, 115, 10, 10),
        )
        with (
            patch("window_auto.workflow.actions.load_template_image"),
            patch(
                "window_auto.workflow.actions.capture_desktop_recognition_frame",
                return_value=frame,
            ),
            patch(
                "window_auto.workflow.actions.recognize_template",
                return_value=recognition,
            ),
        ):
            result = execute_action(
                TemplateMatchStep(
                    id="find",
                    name="Find",
                    template_path=Path("template.png"),
                    result_variable="match",
                    post_action="click",
                ),
                context,
            )

        self.assertEqual(session.controller.calls, [("click", 200, 80, 0)])
        self.assertEqual(result.output["point"], (200, 80))

    def test_template_match_can_press_key_after_recognition(self) -> None:
        session, context = _context()
        recognition = TemplateRecognitionResult(
            hit=True,
            score=0.95,
            box=MatchBox(0, 0, 10, 10),
        )
        with (
            patch("window_auto.workflow.actions.load_template_image"),
            patch(
                "window_auto.workflow.actions.capture_image",
                return_value=numpy.zeros((720, 1280, 3), dtype=numpy.uint8),
            ),
            patch(
                "window_auto.workflow.actions.recognize_template",
                return_value=recognition,
            ),
        ):
            result = execute_action(
                TemplateMatchStep(
                    id="find",
                    name="Find",
                    template_path=Path("template.png"),
                    result_variable="match",
                    post_action="key_press",
                    post_key="F1",
                    post_modifiers=("CTRL",),
                    post_key_hold_ms=0,
                ),
                context,
            )

        self.assertEqual(
            session.controller.calls,
            [
                ("key_down", 0x11),
                ("key_down", 0x70),
                ("key_up", 0x70),
                ("key_up", 0x11),
            ],
        )
        self.assertEqual(result.output["post_action"]["action"], "key_press")

    def test_template_match_error_includes_best_candidate_score(self) -> None:
        session, context = _context()
        recognition = TemplateRecognitionResult(
            hit=False,
            score=None,
            box=None,
            candidate_score=0.451,
            candidate_box=MatchBox(799, 125, 226, 64),
        )
        with (
            patch("window_auto.workflow.actions.load_template_image"),
            patch("window_auto.workflow.actions.capture_image"),
            patch(
                "window_auto.workflow.actions.recognize_template",
                return_value=recognition,
            ),
            self.assertRaises(TemplateNotFoundError) as raised,
        ):
            execute_action(
                TemplateMatchStep(
                    id="find",
                    name="Find",
                    template_path=Path("template.png"),
                    threshold=0.8,
                    attempts=2,
                    interval_ms=0,
                    result_variable="match",
                ),
                context,
            )

        message = str(raised.exception)
        self.assertIn("最接近的候选得分 0.451", message)
        self.assertIn("[799,125,226,64]", message)
        self.assertIn("低于识别阈值 0.800", message)

    def test_zero_attempts_raises_action_error_instead_of_crashing(self) -> None:
        session, context = _context()
        with patch("window_auto.workflow.actions.load_template_image"):
            with self.assertRaisesRegex(WorkflowActionError, "至少为 1"):
                execute_action(
                    TemplateMatchStep(
                        id="find",
                        name="Find",
                        template_path=Path("template.png"),
                        attempts=0,
                        result_variable="match",
                    ),
                    context,
                )

    def test_ocr_match_clicks_recognized_text_center(self) -> None:
        session, context = _context()
        recognition = OcrRecognitionResult(
            hit=True,
            score=0.97,
            box=MatchBox(10, 20, 30, 40),
            text="确定",
        )
        with (
            patch(
                "window_auto.workflow.actions.capture_image",
                return_value=numpy.zeros((720, 1280, 3), dtype=numpy.uint8),
            ),
            patch(
                "window_auto.workflow.actions.recognize_ocr",
                return_value=recognition,
            ) as mocked_ocr,
        ):
            result = execute_action(
                OcrMatchStep(
                    id="find",
                    name="Find",
                    expected=("确定",),
                    result_variable="match",
                    post_action="click",
                ),
                context,
            )

        (_, _, expected, threshold), _ = mocked_ocr.call_args
        self.assertEqual(expected, ("确定",))
        self.assertEqual(threshold, 0.3)
        self.assertEqual(session.controller.calls, [("click", 38, 60, 0)])
        self.assertEqual(context.variables["match"], MatchBox(16, 30, 45, 60))
        self.assertEqual(result.output["text"], "确定")
        self.assertEqual(result.output["post_action"]["action"], "click")

    def test_ocr_match_result_variable_uses_raw_input_coordinates(self) -> None:
        session, context = _context()
        recognition = OcrRecognitionResult(
            hit=True,
            score=0.9,
            box=MatchBox(10, 20, 30, 40),
            text="确定",
        )
        with (
            patch(
                "window_auto.workflow.actions.capture_image",
                return_value=numpy.zeros((720, 1280, 3), dtype=numpy.uint8),
            ),
            patch(
                "window_auto.workflow.actions.recognize_ocr",
                return_value=recognition,
            ),
        ):
            execute_action(
                OcrMatchStep(
                    id="find",
                    name="Find",
                    expected=("确定",),
                    result_variable="document",
                ),
                context,
            )
        result = execute_action(
            MouseClickStep(
                id="open",
                name="Open",
                match_variable="document",
            ),
            context,
        )

        self.assertEqual(session.controller.calls, [("click", 38, 60, 0)])
        self.assertEqual(result.output["point"], (38, 60))

    def test_ocr_match_miss_raises_template_not_found(self) -> None:
        session, context = _context()
        recognition = OcrRecognitionResult(hit=False, score=None, box=None)
        with (
            patch(
                "window_auto.workflow.actions.capture_image",
                return_value=numpy.zeros((720, 1280, 3), dtype=numpy.uint8),
            ),
            patch(
                "window_auto.workflow.actions.recognize_ocr",
                return_value=recognition,
            ),
            self.assertRaises(TemplateNotFoundError) as raised,
        ):
            execute_action(
                OcrMatchStep(
                    id="find",
                    name="Find",
                    expected=("确定", "取消"),
                    attempts=2,
                    interval_ms=0,
                    result_variable="match",
                ),
                context,
            )

        message = str(raised.exception)
        self.assertIn("OCR 识别 2 次", message)
        self.assertIn("“确定”", message)
        self.assertIn("“取消”", message)

    def test_ocr_match_empty_expected_raises_action_error(self) -> None:
        session, context = _context()
        with self.assertRaisesRegex(WorkflowActionError, "期望文本"):
            execute_action(
                OcrMatchStep(
                    id="find",
                    name="Find",
                    expected=(),
                    result_variable="match",
                ),
                context,
            )


class HumanizeActionTests(unittest.TestCase):
    def _context_with_humanize(self, **overrides) -> tuple[_Session, ExecutionContext]:
        session, context = _context()
        humanize = {
            "enabled": True,
            "click_jitter_px": 0,
            "timing_jitter_ratio": 0.0,
            "mouse_curve": False,
        }
        humanize.update(overrides)
        session.config = {"controller": {"humanize": humanize}}
        return session, context

    def test_click_jitter_keeps_point_within_radius(self) -> None:
        session, context = self._context_with_humanize(click_jitter_px=4)
        step = MouseClickStep(id="click", name="Click", x=500, y=300)

        for _ in range(30):
            execute_action(step, context)

        clicks = [call for call in session.controller.calls if call[0] == "click"]
        self.assertEqual(len(clicks), 30)
        for _, x, y, _ in clicks:
            self.assertLessEqual(abs(x - 500), 4)
            self.assertLessEqual(abs(y - 300), 4)
        self.assertGreater(len({(x, y) for _, x, y, _ in clicks}), 1)

    def test_zero_jitter_radius_hits_exact_point(self) -> None:
        session, context = self._context_with_humanize(click_jitter_px=0)

        result = execute_action(
            MouseClickStep(id="click", name="Click", x=30, y=40),
            context,
        )

        self.assertEqual(session.controller.calls, [("click", 30, 40, 0)])
        self.assertEqual(result.output["point"], (30, 40))

    def test_key_hold_is_jittered_within_ratio(self) -> None:
        session, _ = self._context_with_humanize(timing_jitter_ratio=0.5)
        cancellation = Mock()
        context = ExecutionContext(session=session, cancellation=cancellation)

        execute_action(
            KeyPressStep(id="key", name="Key", key="A", hold_ms=100),
            context,
        )

        (hold_seconds,), _ = cancellation.wait.call_args
        self.assertGreaterEqual(hold_seconds, 0.05)
        self.assertLessEqual(hold_seconds, 0.15)

    def test_click_interval_is_jittered_within_ratio(self) -> None:
        session, _ = self._context_with_humanize(timing_jitter_ratio=0.5)
        cancellation = Mock()
        context = ExecutionContext(session=session, cancellation=cancellation)

        execute_action(
            MouseClickStep(id="click", name="Click", x=1, y=1, count=3, interval_ms=100),
            context,
        )

        self.assertEqual(cancellation.wait.call_count, 2)
        for call in cancellation.wait.call_args_list:
            (interval_seconds,), _ = call
            self.assertGreaterEqual(interval_seconds, 0.05)
            self.assertLessEqual(interval_seconds, 0.15)

    def test_text_input_interval_is_jittered_within_ratio(self) -> None:
        session, _ = self._context_with_humanize(timing_jitter_ratio=0.5)
        cancellation = Mock()
        context = ExecutionContext(session=session, cancellation=cancellation)

        execute_action(
            TextInputStep(
                id="text",
                name="Type",
                text="ab",
                strategy="key_sequence",
                interval_ms=100,
            ),
            context,
        )

        self.assertEqual(cancellation.wait.call_count, 2)
        for call in cancellation.wait.call_args_list:
            (interval_seconds,), _ = call
            self.assertGreaterEqual(interval_seconds, 0.05)
            self.assertLessEqual(interval_seconds, 0.15)

    def test_mouse_move_follows_curve_from_known_pointer(self) -> None:
        session, context = self._context_with_humanize(mouse_curve=True)
        context.pointer = (0, 0)

        execute_action(
            MouseMoveStep(id="move", name="Move", x=300, y=0),
            context,
        )

        moves = [call for call in session.controller.calls if call[0] == "move"]
        self.assertGreaterEqual(len(moves), 3)
        self.assertEqual(moves[-1], ("move", 300, 0))
        self.assertEqual(context.pointer, (300, 0))

    def test_first_move_without_known_pointer_jumps_directly(self) -> None:
        session, context = self._context_with_humanize(mouse_curve=True)

        execute_action(
            MouseMoveStep(id="move", name="Move", x=300, y=0),
            context,
        )

        self.assertEqual(session.controller.calls, [("move", 300, 0)])
        self.assertEqual(context.pointer, (300, 0))

    def test_click_glides_pointer_before_clicking(self) -> None:
        session, context = self._context_with_humanize(
            click_jitter_px=0,
            mouse_curve=True,
        )
        context.pointer = (0, 0)

        execute_action(
            MouseClickStep(id="click", name="Click", x=200, y=0),
            context,
        )

        calls = session.controller.calls
        self.assertEqual(calls[-1], ("click", 200, 0, 0))
        self.assertGreater(len(calls), 1)
        self.assertTrue(all(call[0] == "move" for call in calls[:-1]))

    def test_relative_move_advances_known_pointer(self) -> None:
        session, context = self._context_with_humanize(mouse_curve=True)
        context.pointer = (10, 10)

        execute_action(
            MouseMoveStep(
                id="move",
                name="Move",
                move_mode="relative",
                delta_x=5,
                delta_y=-3,
            ),
            context,
        )

        self.assertEqual(session.controller.calls, [("relative_move", 5, -3)])
        self.assertEqual(context.pointer, (15, 7))

    def test_direct_input_receives_humanized_hold_and_curve(self) -> None:
        session, context = self._context_with_humanize(mouse_curve=True)
        session.config["controller"]["direct_screen_input"] = True
        session.window = WindowInfo(
            hwnd=123,
            title="Application",
            class_name="UnrealWindow",
            window_width=1920,
            window_height=1080,
            client_width=1920,
            client_height=1080,
            visible=True,
            minimized=False,
        )

        with patch("window_auto.workflow.actions.click_client_point") as direct_click:
            execute_action(
                MouseClickStep(id="click", name="Click", x=100, y=100),
                context,
            )

        (window, point, button), kwargs = direct_click.call_args
        self.assertIs(window, session.window)
        self.assertEqual(point, (100, 100))
        self.assertEqual(button, "left")
        self.assertGreaterEqual(kwargs["hold_seconds"], 0.04)
        self.assertLessEqual(kwargs["hold_seconds"], 0.12)
        self.assertTrue(kwargs["move_curve"])


class WorkflowV2EngineHumanizeTests(unittest.TestCase):
    def test_pointer_is_carried_across_steps(self) -> None:
        session = _Session()
        session.config = {
            "controller": {
                "humanize": {
                    "enabled": True,
                    "click_jitter_px": 0,
                    "timing_jitter_ratio": 0.0,
                    "mouse_curve": True,
                }
            }
        }
        definition = WorkflowDefinition(
            name="humanized",
            steps=(
                MouseMoveStep(id="move", name="Move", x=10, y=20),
                MouseClickStep(id="click", name="Click", x=200, y=20),
            ),
        )

        result = WorkflowEngine().run(definition, session)

        self.assertTrue(all(step.succeeded for step in result.steps))
        calls = session.controller.calls
        self.assertEqual(calls[0], ("move", 10, 20))
        self.assertEqual(calls[-1], ("click", 200, 20, 0))
        approach = calls[1:-1]
        self.assertGreater(len(approach), 1)
        self.assertTrue(all(call[0] == "move" for call in approach))


class WorkflowV2EngineTests(unittest.TestCase):
    def test_engine_emits_events_and_runs_steps_in_order(self) -> None:
        session = _Session()
        events = []
        definition = WorkflowDefinition(
            name="input",
            steps=(
                MouseMoveStep(id="move", name="Move", x=1, y=2),
                TextInputStep(id="text", name="Text", text="abc"),
            ),
        )

        result = WorkflowEngine(events.append).run(definition, session)

        self.assertFalse(result.cancelled)
        self.assertEqual([item.step_id for item in result.steps], ["move", "text"])
        self.assertEqual(events[0].type, WorkflowEventType.WORKFLOW_STARTED)
        self.assertEqual(events[-1].type, WorkflowEventType.WORKFLOW_SUCCEEDED)

    def test_cancelled_wait_stops_without_later_input(self) -> None:
        session = _Session()
        token = CancellationToken()
        token.cancel()
        definition = WorkflowDefinition(
            name="cancel",
            steps=(
                WaitStep(id="wait", name="Wait", duration_ms=1000),
                TextInputStep(id="text", name="Text", text="must-not-run"),
            ),
        )

        result = WorkflowEngine().run(definition, session, token)

        self.assertTrue(result.cancelled)
        self.assertEqual(session.controller.calls, [])

    def test_stop_policy_raises_after_action_failure(self) -> None:
        session = _Session()
        session.controller.fail_click = True
        definition = WorkflowDefinition(
            name="failure",
            settings=WorkflowSettings(stop_on_error=True),
            steps=(MouseClickStep(id="click", name="Click", x=1, y=2),),
        )

        with self.assertRaises(WorkflowExecutionError):
            WorkflowEngine().run(definition, session)

    def test_retry_policy_repeats_template_step_until_success(self) -> None:
        session = _Session()
        events = []
        definition = WorkflowDefinition(
            name="retry",
            steps=(
                TemplateMatchStep(
                    id="find",
                    name="Find",
                    on_failure="retry",
                    template_path=Path("template.png"),
                    attempts=1,
                    interval_ms=0,
                    result_variable="match",
                ),
            ),
        )
        with patch(
            "window_auto.workflow.engine.execute_action",
            side_effect=(
                TemplateNotFoundError("not found"),
                TemplateNotFoundError("not found"),
                ActionResult({"score": 0.9}),
            ),
        ) as mocked_action:
            result = WorkflowEngine(events.append).run(definition, session)

        self.assertEqual(mocked_action.call_count, 3)
        self.assertTrue(result.steps[0].succeeded)
        self.assertEqual(
            sum(event.type == WorkflowEventType.STEP_FAILED for event in events),
            2,
        )

    def test_default_timeout_fails_a_step_that_runs_too_long(self) -> None:
        session = _Session()

        def stuck(step, context):
            context.cancellation.wait(5.0)

        definition = WorkflowDefinition(
            name="timeout",
            settings=WorkflowSettings(stop_on_error=False, default_timeout_ms=100),
            steps=(MouseClickStep(id="click", name="Click", x=1, y=2),),
        )

        with patch(
            "window_auto.workflow.engine.execute_action", side_effect=stuck
        ):
            started = time.perf_counter()
            result = WorkflowEngine().run(definition, session)
            elapsed = time.perf_counter() - started

        self.assertFalse(result.cancelled)
        self.assertEqual(len(result.steps), 1)
        self.assertFalse(result.steps[0].succeeded)
        self.assertIn("超时", result.steps[0].error)
        self.assertLess(elapsed, 2.0)

    def test_default_timeout_stops_workflow_when_stop_on_error(self) -> None:
        session = _Session()

        def stuck(step, context):
            context.cancellation.wait(5.0)

        definition = WorkflowDefinition(
            name="timeout-stop",
            settings=WorkflowSettings(stop_on_error=True, default_timeout_ms=100),
            steps=(MouseClickStep(id="click", name="Click", x=1, y=2),),
        )

        with patch(
            "window_auto.workflow.engine.execute_action", side_effect=stuck
        ):
            with self.assertRaises(WorkflowExecutionError):
                WorkflowEngine().run(definition, session)

    def test_wait_step_may_exceed_default_timeout(self) -> None:
        session = _Session()
        definition = WorkflowDefinition(
            name="wait-exempt",
            settings=WorkflowSettings(default_timeout_ms=50),
            steps=(WaitStep(id="wait", name="Wait", duration_ms=150),),
        )

        result = WorkflowEngine().run(definition, session)

        self.assertFalse(result.cancelled)
        self.assertTrue(result.steps[0].succeeded)

    def test_user_cancel_still_interrupts_a_timed_step(self) -> None:
        session = _Session()
        token = CancellationToken()
        definition = WorkflowDefinition(
            name="cancel-timed",
            settings=WorkflowSettings(default_timeout_ms=10_000),
            steps=(
                TextInputStep(
                    id="type",
                    name="Type",
                    text="0123456789",
                    interval_ms=200,
                ),
                MouseClickStep(id="click", name="Click", x=1, y=1),
            ),
        )
        threading.Timer(0.15, token.cancel).start()

        result = WorkflowEngine().run(definition, session, token)

        self.assertTrue(result.cancelled)
        self.assertNotIn(("click", 1, 1, 0), session.controller.calls)

    def test_template_polling_budget_extends_the_default_timeout(self) -> None:
        session = _Session()
        miss = TemplateRecognitionResult(hit=False, score=None, box=None)
        definition = WorkflowDefinition(
            name="polling",
            settings=WorkflowSettings(stop_on_error=False, default_timeout_ms=150),
            steps=(
                TemplateMatchStep(
                    id="find",
                    name="Find",
                    on_failure="continue",
                    template_path=Path("template.png"),
                    attempts=3,
                    interval_ms=200,
                    result_variable="match",
                ),
            ),
        )
        with (
            patch("window_auto.workflow.actions.load_template_image"),
            patch(
                "window_auto.workflow.actions.capture_image",
                return_value=numpy.zeros((720, 1280, 3), dtype=numpy.uint8),
            ),
            patch("window_auto.workflow.actions.recognize_template", return_value=miss),
        ):
            started = time.perf_counter()
            result = WorkflowEngine().run(definition, session)
            elapsed = time.perf_counter() - started

        # The step's own polling budget (3 x 200 ms) extends the 150 ms default,
        # so all three attempts run and the step reports "not found".
        self.assertGreaterEqual(elapsed, 0.35)
        self.assertFalse(result.steps[0].succeeded)
        self.assertIn("未找到模板", result.steps[0].error)
        self.assertNotIn("超时", result.steps[0].error)


def _write_settings_workflow(root: Path, settings: dict) -> Path:
    path = root / "workflow.json"
    path.write_text(
        json.dumps(
            {
                "version": 2,
                "name": "auto delay",
                "settings": settings,
                "steps": [
                    {"id": "click", "type": "mouse_click", "name": "click", "x": 1, "y": 1}
                ],
            }
        ),
        encoding="utf-8",
    )
    return path


class AutoDelayLoaderTests(unittest.TestCase):
    def test_auto_delay_defaults_to_none(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            definition = load_workflow_v2(_write_settings_workflow(root, {}), root)

        self.assertEqual(definition.settings.auto_delay.mode, "none")

    def test_fixed_auto_delay_is_loaded(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            definition = load_workflow_v2(
                _write_settings_workflow(
                    root, {"auto_delay": {"mode": "fixed", "fixed_ms": 250}}
                ),
                root,
            )

        self.assertEqual(definition.settings.auto_delay.mode, "fixed")
        self.assertEqual(definition.settings.auto_delay.fixed_ms, 250)

    def test_random_auto_delay_is_loaded(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            definition = load_workflow_v2(
                _write_settings_workflow(
                    root,
                    {"auto_delay": {"mode": "random", "min_ms": 100, "max_ms": 900}},
                ),
                root,
            )

        self.assertEqual(definition.settings.auto_delay.mode, "random")
        self.assertEqual(definition.settings.auto_delay.min_ms, 100)
        self.assertEqual(definition.settings.auto_delay.max_ms, 900)

    def test_auto_delay_rejects_unknown_mode(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            path = _write_settings_workflow(
                root, {"auto_delay": {"mode": "chaotic", "fixed_ms": 100}}
            )

            with self.assertRaises(WorkflowV2ConfigError):
                load_workflow_v2(path, root)

    def test_auto_delay_rejects_min_above_max(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            path = _write_settings_workflow(
                root, {"auto_delay": {"mode": "random", "min_ms": 900, "max_ms": 100}}
            )

            with self.assertRaises(WorkflowV2ConfigError):
                load_workflow_v2(path, root)

    def test_auto_delay_rejects_unknown_fields(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            path = _write_settings_workflow(
                root, {"auto_delay": {"mode": "fixed", "fixed_ms": 100, "typo": 1}}
            )

            with self.assertRaises(WorkflowV2ConfigError):
                load_workflow_v2(path, root)


class _RecordingToken(CancellationToken):
    def __init__(self) -> None:
        super().__init__()
        self.waits: list[float] = []

    def wait(self, seconds: float) -> None:
        self.waits.append(seconds)
        super().wait(seconds)


class AutoDelayEngineTests(unittest.TestCase):
    def _two_click_definition(self, auto_delay: AutoDelay) -> WorkflowDefinition:
        return WorkflowDefinition(
            name="auto-delay",
            settings=WorkflowSettings(auto_delay=auto_delay),
            steps=(
                MouseClickStep(id="a", name="A", x=1, y=1),
                MouseClickStep(id="b", name="B", x=2, y=2),
            ),
        )

    def test_fixed_auto_delay_waits_once_between_two_steps(self) -> None:
        token = _RecordingToken()
        definition = self._two_click_definition(AutoDelay(mode="fixed", fixed_ms=60))

        WorkflowEngine().run(definition, _Session(), token)

        self.assertEqual(len(token.waits), 1)
        self.assertAlmostEqual(token.waits[0], 0.06, places=3)

    def test_no_auto_delay_when_mode_is_none(self) -> None:
        token = _RecordingToken()
        definition = self._two_click_definition(AutoDelay(mode="none"))

        WorkflowEngine().run(definition, _Session(), token)

        self.assertEqual(token.waits, [])

    def test_random_auto_delay_stays_within_range(self) -> None:
        token = _RecordingToken()
        definition = self._two_click_definition(
            AutoDelay(mode="random", min_ms=40, max_ms=40)
        )

        WorkflowEngine().run(definition, _Session(), token)

        self.assertEqual(len(token.waits), 1)
        self.assertAlmostEqual(token.waits[0], 0.04, places=3)

    def test_auto_delay_emits_event(self) -> None:
        events = []
        definition = self._two_click_definition(AutoDelay(mode="fixed", fixed_ms=10))

        WorkflowEngine(events.append).run(definition, _Session())

        delay_events = [
            event for event in events if event.type == WorkflowEventType.AUTO_DELAY
        ]
        self.assertEqual(len(delay_events), 1)
        self.assertIn("10", delay_events[0].message)

    def test_random_source_is_unpredictable_system_random(self) -> None:
        import random

        from window_auto.workflow import actions, engine

        self.assertIsInstance(engine._AUTO_DELAY_RANDOM, random.SystemRandom)
        self.assertIsInstance(actions._WAIT_RANDOM, random.SystemRandom)


def _write_workflow_file(
    root: Path,
    filename: str,
    steps: list[dict],
    *,
    name: str = "workflow",
    settings: dict | None = None,
) -> Path:
    data: dict = {"version": 2, "name": name, "steps": steps}
    if settings is not None:
        data["settings"] = settings
    path = root / filename
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return path


def _run_workflow_step(step_id: str, workflow: str, **extra) -> dict:
    return {
        "id": step_id,
        "type": "run_workflow",
        "name": step_id,
        "workflow": workflow,
        **extra,
    }


class RunWorkflowLoaderTests(unittest.TestCase):
    def test_run_workflow_step_is_loaded(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            _write_workflow_file(
                root,
                "child.json",
                [{"id": "w", "type": "wait", "name": "W", "duration_ms": 1}],
            )
            path = _write_workflow_file(
                root, "parent.json", [_run_workflow_step("run", "child.json")]
            )

            definition = load_workflow_v2(path, root)

            step = definition.steps[0]
            self.assertIsInstance(step, RunWorkflowStep)
            self.assertEqual(step.workflow_path, (root / "child.json").resolve())

    def test_run_workflow_prefers_the_workflow_directory(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            workflow_dir = root / "workflow"
            workflow_dir.mkdir()
            _write_workflow_file(
                workflow_dir,
                "child.json",
                [{"id": "w", "type": "wait", "name": "W", "duration_ms": 1}],
            )
            path = _write_workflow_file(
                root, "parent.json", [_run_workflow_step("run", "child.json")]
            )

            with patch(
                "window_auto.workflow.loader.workflow_dir", return_value=workflow_dir
            ):
                definition = load_workflow_v2(path, root)

            self.assertEqual(
                definition.steps[0].workflow_path,
                (workflow_dir / "child.json").resolve(),
            )

    def test_run_workflow_requires_an_existing_file(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            path = _write_workflow_file(
                root, "parent.json", [_run_workflow_step("run", "missing.json")]
            )

            with self.assertRaisesRegex(WorkflowV2ConfigError, "does not exist"):
                load_workflow_v2(path, root)

    def test_run_workflow_rejects_unknown_fields(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            path = _write_workflow_file(
                root,
                "parent.json",
                [_run_workflow_step("run", "child.json", timeout_ms=5)],
            )

            with self.assertRaisesRegex(WorkflowV2ConfigError, "Unknown"):
                load_workflow_v2(path, root)

    def test_run_workflow_rejects_retry_failure_policy(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            path = _write_workflow_file(
                root,
                "parent.json",
                [_run_workflow_step("run", "child.json", on_failure="retry")],
            )

            with self.assertRaisesRegex(WorkflowV2ConfigError, "on_failure"):
                load_workflow_v2(path, root)

    def test_run_workflow_rejects_direct_self_reference(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            path = _write_workflow_file(
                root, "parent.json", [_run_workflow_step("run", "parent.json")]
            )

            with self.assertRaisesRegex(WorkflowV2ConfigError, "itself"):
                load_workflow_v2(path, root)


class RunWorkflowEngineTests(unittest.TestCase):
    def _write_child_click(self, root: Path, filename: str = "child.json") -> Path:
        return _write_workflow_file(
            root,
            filename,
            [{"id": "click", "type": "mouse_click", "name": "Click", "x": 7, "y": 9}],
            name="child",
        )

    def test_sub_workflow_steps_run_inline(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            self._write_child_click(root)
            parent_path = _write_workflow_file(
                root,
                "parent.json",
                [
                    {"id": "w", "type": "wait", "name": "W", "duration_ms": 1},
                    _run_workflow_step("run", "child.json"),
                ],
                name="parent",
            )
            session = _Session()
            events = []
            definition = load_workflow_v2(parent_path, root)

            result = WorkflowEngine(events.append).run(definition, session)

            self.assertIn(("click", 7, 9, 0), session.controller.calls)
            self.assertTrue(result.steps[-1].succeeded)
            self.assertIn("子工作流", result.steps[-1].output)
            started_names = [
                event.workflow_name
                for event in events
                if event.type == WorkflowEventType.WORKFLOW_STARTED
            ]
            self.assertEqual(started_names, ["parent", "child"])

    def test_variables_are_shared_with_sub_workflow(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            child_path = _write_workflow_file(
                root,
                "child.json",
                [{"id": "key", "type": "key_press", "name": "Key", "key": "ENTER"}],
            )
            observed: list[bool] = []

            def fake_action(step, context):
                if step.kind == "text_input":
                    context.variables["shared"] = "yes"
                if step.kind == "key_press":
                    observed.append("shared" in context.variables)
                return ActionResult(None)

            definition = WorkflowDefinition(
                name="parent",
                steps=(
                    TextInputStep(id="type", name="Type", text="abc"),
                    RunWorkflowStep(id="run", name="Run", workflow_path=child_path),
                ),
            )

            with patch(
                "window_auto.workflow.engine.execute_action", side_effect=fake_action
            ):
                result = WorkflowEngine().run(definition, _Session())

            self.assertEqual(observed, [True])
            self.assertTrue(all(step.succeeded for step in result.steps))

    def test_sub_workflow_failure_raises_with_stop_policy(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            self._write_child_click(root)
            parent_path = _write_workflow_file(
                root, "parent.json", [_run_workflow_step("run", "child.json")]
            )
            session = _Session()
            session.controller.fail_click = True
            definition = load_workflow_v2(parent_path, root)

            with self.assertRaises(WorkflowExecutionError):
                WorkflowEngine().run(definition, session)

    def test_parent_continue_policy_survives_sub_workflow_failure(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            self._write_child_click(root)
            parent_path = _write_workflow_file(
                root,
                "parent.json",
                [
                    _run_workflow_step("run", "child.json", on_failure="continue"),
                    {"id": "after", "type": "wait", "name": "W", "duration_ms": 1},
                ],
            )
            session = _Session()
            session.controller.fail_click = True
            definition = load_workflow_v2(parent_path, root)

            result = WorkflowEngine().run(definition, session)

            self.assertFalse(result.steps[0].succeeded)
            self.assertTrue(result.steps[1].succeeded)

    def test_circular_sub_workflow_references_are_rejected(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            _write_workflow_file(
                root, "a.json", [_run_workflow_step("run-b", "b.json")], name="A"
            )
            _write_workflow_file(
                root, "b.json", [_run_workflow_step("run-a", "a.json")], name="B"
            )
            definition = load_workflow_v2(root / "a.json", root)

            with self.assertRaisesRegex(WorkflowExecutionError, "循环调用"):
                WorkflowEngine().run(definition, _Session())

    def test_nesting_depth_limit_is_enforced(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            _write_workflow_file(
                root,
                "f4.json",
                [{"id": "w", "type": "wait", "name": "W", "duration_ms": 1}],
            )
            for index in (3, 2, 1):
                _write_workflow_file(
                    root,
                    f"f{index}.json",
                    [_run_workflow_step("run", f"f{index + 1}.json")],
                )
            definition = WorkflowDefinition(
                name="parent",
                steps=(
                    RunWorkflowStep(
                        id="run",
                        name="Run",
                        workflow_path=(root / "f1.json").resolve(),
                    ),
                ),
            )

            with patch("window_auto.workflow.engine.MAX_SUB_WORKFLOW_DEPTH", 3):
                with self.assertRaisesRegex(WorkflowExecutionError, "上限"):
                    WorkflowEngine().run(definition, _Session())

    def test_sub_workflow_step_is_exempt_from_parent_timeout(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            _write_workflow_file(
                root,
                "child.json",
                [{"id": "w", "type": "wait", "name": "W", "duration_ms": 250}],
            )
            parent_path = _write_workflow_file(
                root,
                "parent.json",
                [_run_workflow_step("run", "child.json")],
                settings={"default_timeout_ms": 100},
            )
            definition = load_workflow_v2(parent_path, root)

            started = time.perf_counter()
            result = WorkflowEngine().run(definition, _Session())
            elapsed = time.perf_counter() - started

            self.assertTrue(result.steps[0].succeeded)
            self.assertGreaterEqual(elapsed, 0.2)

    def test_cancellation_propagates_into_sub_workflow(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            _write_workflow_file(
                root,
                "child.json",
                [{"id": "w", "type": "wait", "name": "W", "duration_ms": 5000}],
            )
            parent_path = _write_workflow_file(
                root, "parent.json", [_run_workflow_step("run", "child.json")]
            )
            definition = load_workflow_v2(parent_path, root)
            token = CancellationToken()
            threading.Timer(0.1, token.cancel).start()

            started = time.perf_counter()
            result = WorkflowEngine().run(definition, _Session(), token)
            elapsed = time.perf_counter() - started

            self.assertTrue(result.cancelled)
            self.assertLess(elapsed, 2.0)


if __name__ == "__main__":
    unittest.main()
