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


if __name__ == "__main__":
    unittest.main()
