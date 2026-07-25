import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import Mock, patch

import numpy
from PIL import Image

from nzm_auto.diagnostics.desktop_scope import DesktopRecognitionFrame
from nzm_auto.diagnostics.template_match import MatchBox, TemplateRecognitionResult
from nzm_auto.windowing.discovery import WindowInfo
from nzm_auto.workflow.actions import (
    ActionResult,
    TemplateNotFoundError,
    WorkflowActionError,
    execute_action,
)
from nzm_auto.workflow.context import CancellationToken, ExecutionContext
from nzm_auto.workflow.engine import WorkflowEngine, WorkflowExecutionError
from nzm_auto.workflow.events import WorkflowEventType
from nzm_auto.workflow.loader import WorkflowV2ConfigError, load_workflow_v2
from nzm_auto.workflow.model import (
    KeyPressStep,
    MouseClickStep,
    MouseMoveStep,
    TemplateMatchStep,
    TextInputStep,
    WaitStep,
    WorkflowDefinition,
    WorkflowSettings,
)
from nzm_auto.workflow.virtual_keys import resolve_text_character, resolve_virtual_key


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
                "target": {"title_pattern": "逆战：未来", "class_name": "CabinetWClass"},
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
                        "text": "NZM automation test",
                    },
                ],
            }
            path = root / "workflow.json"
            path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

            definition = load_workflow_v2(path, root)

            self.assertEqual(definition.name, "GUI workflow")
            self.assertEqual(definition.target.title_pattern, "逆战：未来")
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

    def test_precise_game_click_bypasses_controller_coordinate_mapping(self) -> None:
        session, context = _context()
        session.config = {"controller": {"direct_screen_input": True}}
        session.window = WindowInfo(
            hwnd=123,
            title="Game",
            class_name="UnrealWindow",
            window_width=1920,
            window_height=1080,
            client_width=1920,
            client_height=1080,
            visible=True,
            minimized=False,
        )

        with patch("nzm_auto.workflow.actions.click_client_point") as direct_click:
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

    def test_precise_game_click_bypasses_controller_coordinate_mapping(self) -> None:
        session, context = _context()
        session.config = {"controller": {"direct_screen_input": True}}
        session.window = WindowInfo(
            hwnd=123,
            title="Game",
            class_name="UnrealWindow",
            window_width=1920,
            window_height=1080,
            client_width=1920,
            client_height=1080,
            visible=True,
            minimized=False,
        )

        with patch("nzm_auto.workflow.actions.click_client_point") as direct_click:
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
        with patch("nzm_auto.workflow.actions.randint", return_value=275) as random_value:
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
            patch("nzm_auto.workflow.actions.load_template_image"),
            patch(
                "nzm_auto.workflow.actions.capture_image",
                return_value=numpy.zeros((720, 1280, 3), dtype=numpy.uint8),
            ),
            patch(
                "nzm_auto.workflow.actions.recognize_template",
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
            patch("nzm_auto.workflow.actions.load_template_image"),
            patch(
                "nzm_auto.workflow.actions.capture_image",
                return_value=numpy.zeros((720, 1280, 3), dtype=numpy.uint8),
            ),
            patch(
                "nzm_auto.workflow.actions.recognize_template",
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
            patch("nzm_auto.workflow.actions.load_template_image"),
            patch(
                "nzm_auto.workflow.actions.capture_desktop_recognition_frame",
                return_value=frame,
            ),
            patch(
                "nzm_auto.workflow.actions.recognize_template",
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
            patch("nzm_auto.workflow.actions.load_template_image"),
            patch(
                "nzm_auto.workflow.actions.capture_image",
                return_value=numpy.zeros((720, 1280, 3), dtype=numpy.uint8),
            ),
            patch(
                "nzm_auto.workflow.actions.recognize_template",
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
            patch("nzm_auto.workflow.actions.load_template_image"),
            patch("nzm_auto.workflow.actions.capture_image"),
            patch(
                "nzm_auto.workflow.actions.recognize_template",
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
        self.assertIn("Best candidate score 0.451", message)
        self.assertIn("[799,125,226,64]", message)
        self.assertIn("threshold 0.800", message)


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
            "nzm_auto.workflow.engine.execute_action",
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


if __name__ == "__main__":
    unittest.main()
