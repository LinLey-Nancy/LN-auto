"""Command-line entry points for the framework."""

from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path
import sys

from window_auto.application.input_profiles import InputProfileName, get_input_profile
from window_auto.application.session import AutomationSession
from window_auto.application.window_service import WindowQuery, list_windows
from window_auto.automation.template_action import (
    TemplateActionError,
    load_template_image,
    run_template_action,
)
from window_auto.automation.workflow import (
    WorkflowConfigError,
    WorkflowExecutionError,
    load_workflow,
    run_workflow,
)
from window_auto.config.loader import load_config
from window_auto.diagnostics.screenshot import ScreenshotError, capture_image, capture_screenshot
from window_auto.diagnostics.input_test import InputTestError, run_input_test
from window_auto.diagnostics.template_match import (
    TemplateMatchDiagnosticError,
    crop_template,
    run_template_match,
)
from window_auto.diagnostics.workspace import create_debug_workspace, configure_file_logging
from window_auto.runtime.maa_runtime import get_maa_version
from window_auto.runtime.task_runtime import TaskRuntimeError, run_task
from window_auto.runtime.win32_controller import ControllerConnectionError
from window_auto.paths import project_root, workflow_dir
from window_auto.windowing.selector import (
    WindowSelectionError,
    choose_window_by_index,
    select_target_window,
)
from window_auto.workflow.engine import (
    WorkflowEngine,
    WorkflowExecutionError as WorkflowV2ExecutionError,
)
from window_auto.workflow.events import WorkflowEventType
from window_auto.workflow.loader import WorkflowV2ConfigError, load_workflow_v2


PROJECT_ROOT = project_root()
WORKFLOW_DIRECTORY = workflow_dir()
DEFAULT_CONFIG_PATH = PROJECT_ROOT / "config" / "default.json"


class CliConfigError(RuntimeError):
    """Raised when the main configuration cannot be loaded or validated."""


def resolve_workflow_path(path: Path) -> Path:
    """Resolve a workflow path, preferring the user workflow directory."""
    if path.is_absolute():
        return path
    candidate = WORKFLOW_DIRECTORY / path
    if candidate.is_file():
        return candidate
    return PROJECT_ROOT / path


def _load_cli_config(config_path: Path) -> dict:
    try:
        return load_config(config_path)
    except (OSError, ValueError) as error:
        raise CliConfigError(f"Configuration failed: {error}") from error


def _read_stdin_line() -> str | None:
    """Read one interactive input line, or None when stdin is unavailable."""
    if sys.stdin is None:
        return None
    try:
        return sys.stdin.readline().strip()
    except (OSError, ValueError):
        return None


def configure_console() -> None:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(errors="replace")


def single_line(value: str) -> str:
    return value.replace("\t", " ").replace("\r", " ").replace("\n", " ")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="ln-auto")
    subparsers = parser.add_subparsers(dest="command", required=True)

    self_test = subparsers.add_parser(
        "self-test", help="Validate the framework files and default configuration."
    )
    self_test.add_argument(
        "--config", type=Path, default=DEFAULT_CONFIG_PATH, help="Path to a JSON config file."
    )

    subparsers.add_parser(
        "maa-version", help="Load MaaFramework and print its native runtime version."
    )

    run = subparsers.add_parser(
        "run", help="Choose a window and verify the Maa Win32 controller connection."
    )
    run.add_argument(
        "--config", type=Path, default=DEFAULT_CONFIG_PATH, help="Path to a JSON config file."
    )
    run.add_argument("--title", help="Optional title substring filter.")
    run.add_argument("--class-name", help="Optional window class substring filter.")
    run.add_argument(
        "--visible-only", action="store_true", help="Only show currently visible windows."
    )
    run.add_argument("--index", type=int, help="Choose an index without an interactive prompt.")

    capture = subparsers.add_parser(
        "capture", help="Choose a window, connect, and save one debug screenshot."
    )
    capture.add_argument(
        "--config", type=Path, default=DEFAULT_CONFIG_PATH, help="Path to a JSON config file."
    )
    capture.add_argument("--title", help="Optional title substring filter.")
    capture.add_argument("--class-name", help="Optional window class substring filter.")
    capture.add_argument(
        "--visible-only", action="store_true", help="Only show currently visible windows."
    )
    capture.add_argument(
        "--index", type=int, help="Choose an index without an interactive prompt."
    )

    template_match = subparsers.add_parser(
        "template-match", help="Crop a temporary template and run Maa TemplateMatch."
    )
    template_match.add_argument(
        "--config", type=Path, default=DEFAULT_CONFIG_PATH, help="Path to a JSON config file."
    )
    template_match.add_argument("--title", help="Optional title substring filter.")
    template_match.add_argument("--class-name", help="Optional window class substring filter.")
    template_match.add_argument(
        "--visible-only", action="store_true", help="Only show currently visible windows."
    )
    template_match.add_argument(
        "--index", type=int, help="Choose an index without an interactive prompt."
    )
    template_match.add_argument(
        "--template-roi",
        nargs=4,
        type=int,
        metavar=("X", "Y", "WIDTH", "HEIGHT"),
        required=True,
        help="Crop rectangle in Maa screenshot coordinates.",
    )
    template_match.add_argument(
        "--threshold", type=float, default=0.8, help="TemplateMatch threshold, default 0.8."
    )

    input_test = subparsers.add_parser(
        "input-test", help="Send one explicit double-click and verify the visual change."
    )
    input_test.add_argument(
        "--config", type=Path, default=DEFAULT_CONFIG_PATH, help="Path to a JSON config file."
    )
    input_test.add_argument("--title", help="Optional title substring filter.")
    input_test.add_argument("--class-name", help="Optional window class substring filter.")
    input_test.add_argument(
        "--visible-only", action="store_true", help="Only show currently visible windows."
    )
    input_test.add_argument("--index", type=int, help="Choose an index without an interactive prompt.")
    input_test.add_argument(
        "--point",
        nargs=2,
        type=int,
        metavar=("X", "Y"),
        required=True,
        help="Click point in Maa screenshot coordinates.",
    )
    input_test.add_argument(
        "--yes", action="store_true", help="Confirm the double-click without an interactive prompt."
    )

    template_action = subparsers.add_parser(
        "template-action",
        help="Recognize a template, click its center, and verify the visual result.",
    )
    template_action.add_argument(
        "--config", type=Path, default=DEFAULT_CONFIG_PATH, help="Path to a JSON config file."
    )
    template_action.add_argument("--title", help="Optional title substring filter.")
    template_action.add_argument("--class-name", help="Optional window class substring filter.")
    template_action.add_argument(
        "--visible-only", action="store_true", help="Only show currently visible windows."
    )
    template_action.add_argument(
        "--index", type=int, help="Choose an index without an interactive prompt."
    )
    template_source = template_action.add_mutually_exclusive_group(required=True)
    template_source.add_argument(
        "--template",
        type=Path,
        help="Existing PNG template; relative paths are resolved from the project root.",
    )
    template_source.add_argument(
        "--template-roi",
        nargs=4,
        type=int,
        metavar=("X", "Y", "WIDTH", "HEIGHT"),
        help="Diagnostic-only in-memory template crop in Maa screenshot coordinates.",
    )
    template_action.add_argument(
        "--threshold", type=float, default=0.8, help="TemplateMatch threshold, default 0.8."
    )
    template_action.add_argument(
        "--action", choices=("click", "double-click"), required=True, help="Input to perform."
    )
    template_action.add_argument(
        "--yes", action="store_true", help="Confirm input without an interactive prompt."
    )

    workflow_run = subparsers.add_parser(
        "workflow-run", help="Execute a validated sequence of template-driven actions."
    )
    workflow_run.add_argument(
        "--config", type=Path, default=DEFAULT_CONFIG_PATH, help="Path to a JSON config file."
    )
    workflow_run.add_argument(
        "--workflow", type=Path, required=True, help="Path to a workflow JSON file."
    )
    workflow_run.add_argument("--title", help="Optional title substring filter.")
    workflow_run.add_argument("--class-name", help="Optional window class substring filter.")
    workflow_run.add_argument(
        "--visible-only", action="store_true", help="Only show currently visible windows."
    )
    workflow_run.add_argument(
        "--index", type=int, help="Choose an index without an interactive prompt."
    )
    workflow_run.add_argument(
        "--yes", action="store_true", help="Confirm the complete workflow without a prompt."
    )

    workflow_run_v2 = subparsers.add_parser(
        "workflow-run-v2",
        help="Execute a version 2 workflow with independent recognition and input steps.",
    )
    workflow_run_v2.add_argument(
        "--config", type=Path, default=DEFAULT_CONFIG_PATH, help="Path to a JSON config file."
    )
    workflow_run_v2.add_argument(
        "--workflow", type=Path, required=True, help="Path to a version 2 workflow JSON file."
    )
    workflow_run_v2.add_argument("--title", help="Override the workflow target title filter.")
    workflow_run_v2.add_argument(
        "--class-name", help="Override the workflow target class filter."
    )
    workflow_run_v2.add_argument(
        "--visible-only", action="store_true", help="Only show currently visible windows."
    )
    workflow_run_v2.add_argument(
        "--index", type=int, help="Choose an index without an interactive prompt."
    )
    workflow_run_v2.add_argument(
        "--input-profile",
        choices=tuple(profile.value for profile in InputProfileName),
        default=InputProfileName.FOREGROUND_PRECISE.value,
        help="Win32 input compatibility profile.",
    )
    workflow_run_v2.add_argument(
        "--yes", action="store_true", help="Confirm the complete workflow without a prompt."
    )

    windows = subparsers.add_parser("windows", help="Read-only desktop window tools.")
    window_commands = windows.add_subparsers(dest="windows_command", required=True)
    window_list = window_commands.add_parser("list", help="List desktop windows.")
    window_list.add_argument("--title", help="Case-insensitive title substring filter.")
    window_list.add_argument(
        "--class-name", help="Case-insensitive window class substring filter."
    )
    window_list.add_argument("--json", action="store_true", help="Print JSON output.")
    window_select = window_commands.add_parser(
        "select", help="Select exactly one target window using configuration."
    )
    window_select.add_argument(
        "--config", type=Path, default=DEFAULT_CONFIG_PATH, help="Path to a JSON config file."
    )
    window_select.add_argument("--json", action="store_true", help="Print JSON output.")
    window_choose = window_commands.add_parser(
        "choose", help="List candidate windows and choose one by index."
    )
    window_choose.add_argument("--title", help="Optional title substring filter.")
    window_choose.add_argument("--class-name", help="Optional window class substring filter.")
    window_choose.add_argument(
        "--visible-only", action="store_true", help="Only show currently visible windows."
    )
    window_choose.add_argument(
        "--index", type=int, help="Choose this index without an interactive prompt."
    )
    window_choose.add_argument("--json", action="store_true", help="Print selection as JSON.")
    return parser


def print_window_table(windows: list, file=None) -> None:
    print("INDEX\tHWND\tVISIBLE\tMINIMIZED\tWINDOW\tCLIENT\tCLASS\tTITLE", file=file)
    for index, window in enumerate(windows):
        window_size = f"{window.window_width}x{window.window_height}"
        client_size = f"{window.client_width}x{window.client_height}"
        print(
            f"{index}\t0x{window.hwnd:X}\t{window.visible}\t{window.minimized}"
            f"\t{window_size}\t{client_size}\t{single_line(window.class_name)}"
            f"\t{single_line(window.title)}",
            file=file,
        )
    print(f"Total: {len(windows)}", file=file)


def run_window_list(
    title_filter: str | None,
    class_filter: str | None,
    as_json: bool,
) -> int:
    windows = list_windows(WindowQuery(title_filter, class_filter))
    if as_json:
        print(json.dumps([window.to_dict() for window in windows], ensure_ascii=False, indent=2))
        return 0

    print_window_table(windows)
    print("Read-only enumeration completed. No controller was created and no input was sent.")
    return 0


def run_window_choose(
    title_filter: str | None,
    class_filter: str | None,
    visible_only: bool,
    selected_index: int | None,
    as_json: bool,
) -> int:
    windows = list_windows(WindowQuery(title_filter, class_filter, visible_only))

    if not windows:
        print("Window selection failed: no candidate windows are available.", file=sys.stderr)
        return 2

    if not as_json:
        print_window_table(windows)
    elif selected_index is None:
        # Interactive JSON mode: the candidate table goes to stderr so that
        # stdout carries only the final JSON document for pipe consumers.
        print_window_table(windows, file=sys.stderr)

    if selected_index is None:
        print("Choose window index: ", end="", file=sys.stderr, flush=True)
        value = _read_stdin_line()
        if value is None:
            print(
                "Window selection failed: no interactive input is available; "
                "use --index instead.",
                file=sys.stderr,
            )
            return 2
        try:
            selected_index = int(value)
        except ValueError:
            print(f"Window selection failed: {value!r} is not an integer index.", file=sys.stderr)
            return 2

    try:
        window = choose_window_by_index(windows, selected_index)
    except WindowSelectionError as error:
        print(f"Window selection failed: {error}", file=sys.stderr)
        return 2

    if as_json:
        print(json.dumps(window.to_dict(), ensure_ascii=False, indent=2))
    else:
        print(f"Selected: 0x{window.hwnd:X} {window.class_name} {window.title}")
        print("Selection was read-only. No controller was created and no input was sent.")
    return 0


def choose_window_for_run(
    title_filter: str | None,
    class_filter: str | None,
    visible_only: bool,
    selected_index: int | None,
):
    windows = list_windows(WindowQuery(title_filter, class_filter, visible_only))
    if not windows:
        raise WindowSelectionError("No candidate windows are available.")

    print_window_table(windows)
    if selected_index is None:
        print("Choose window index: ", end="", file=sys.stderr, flush=True)
        value = _read_stdin_line()
        if value is None:
            raise WindowSelectionError(
                "No interactive input is available; use --index instead."
            )
        try:
            selected_index = int(value)
        except ValueError as error:
            raise WindowSelectionError(f"{value!r} is not an integer index.") from error
    return choose_window_by_index(windows, selected_index)


def run_program(
    config_path: Path,
    title_filter: str | None,
    class_filter: str | None,
    visible_only: bool,
    selected_index: int | None,
    capture_requested: bool = False,
) -> int:
    config = _load_cli_config(config_path)
    workspace = create_debug_workspace(
        PROJECT_ROOT,
        config["diagnostics"]["debug_dir"],
    )
    log_path = configure_file_logging(workspace)
    logger = logging.getLogger(__name__)
    logger.info("Program start; capture_requested=%s", capture_requested)
    print(f"Debug log: {log_path}")
    print(f"MaaFramework: {get_maa_version()}")

    try:
        window = choose_window_for_run(
            title_filter,
            class_filter,
            visible_only,
            selected_index,
        )
    except WindowSelectionError as error:
        print(f"Window selection failed: {error}", file=sys.stderr)
        return 2

    print(f"Selected: 0x{window.hwnd:X} {window.class_name} {window.title}")
    logger.info(
        "Selected window hwnd=0x%X class=%r title=%r",
        window.hwnd,
        window.class_name,
        window.title,
    )
    session = None
    exit_code = 0
    try:
        session = AutomationSession.connect(window, config, PROJECT_ROOT, workspace)
        controller = session.controller
        print("Win32 controller connected successfully.")
        logger.info("Win32 controller connected")
        if capture_requested:
            screenshot_path = workspace.timestamped_path(
                workspace.screenshots,
                "window",
                ".png",
            )
            result = capture_screenshot(controller, screenshot_path)
            print(f"Screenshot: {result.path}")
            print(f"Screenshot size: {result.width}x{result.height}x{result.channels}")
            logger.info(
                "Screenshot saved path=%s size=%sx%s channels=%s",
                result.path,
                result.width,
                result.height,
                result.channels,
            )
        else:
            task_runtime = session.initialize_runtime()
            print(f"Resource bundle loaded: {session.resource_path}")
            print("Tasker initialized successfully.")
            task_entry = config["runtime"]["task_entry"]
            run_task(
                task_runtime,
                task_entry,
                config["runtime"]["task_timeout_seconds"],
            )
            print(f"Pipeline task succeeded: {task_entry}")
            print("The self-test task performed no click or keyboard input.")
            logger.info("Pipeline task succeeded entry=%s", task_entry)
    except ControllerConnectionError as error:
        print(f"Controller connection failed: {error}", file=sys.stderr)
        logger.exception("Controller connection failed")
        exit_code = 3
    except ScreenshotError as error:
        print(f"Screenshot failed: {error}", file=sys.stderr)
        logger.exception("Screenshot failed")
        exit_code = 5
    except TaskRuntimeError as error:
        print(f"Task runtime failed: {error}", file=sys.stderr)
        logger.exception("Task runtime failed")
        exit_code = 6
    finally:
        if session is not None:
            try:
                session.close()
                print("Win32 controller deactivated successfully.")
                logger.info("Win32 controller deactivated")
            except ControllerConnectionError as error:
                print(f"Controller cleanup failed: {error}", file=sys.stderr)
                logger.exception("Controller cleanup failed")
                exit_code = 4
    return exit_code


def run_template_match_program(args) -> int:
    config = _load_cli_config(args.config)
    workspace = create_debug_workspace(PROJECT_ROOT, config["diagnostics"]["debug_dir"])
    log_path = configure_file_logging(workspace)
    logger = logging.getLogger(__name__)
    print(f"Debug log: {log_path}")
    print(f"MaaFramework: {get_maa_version()}")

    try:
        window = choose_window_for_run(
            args.title,
            args.class_name,
            args.visible_only,
            args.index,
        )
    except WindowSelectionError as error:
        print(f"Window selection failed: {error}", file=sys.stderr)
        return 2

    print(f"Selected: 0x{window.hwnd:X} {window.class_name} {window.title}")
    session = None
    exit_code = 0
    try:
        session = AutomationSession.connect(window, config, PROJECT_ROOT, workspace)
        controller = session.controller
        runtime = session.initialize_runtime()
        image = capture_image(controller)

        annotated_path = workspace.timestamped_path(
            workspace.screenshots, "template-match", ".png"
        )
        report_path = workspace.timestamped_path(workspace.reports, "template-match", ".json")
        result = run_template_match(
            runtime,
            image,
            tuple(args.template_roi),
            args.threshold,
            annotated_path,
            report_path,
        )
        print(f"TemplateMatch hit: {result.hit}")
        print(f"Score: {result.score}")
        print(f"Box: {result.box}")
        print(f"Annotated image: {result.annotated_path}")
        print(f"Report: {result.report_path}")
        logger.info("TemplateMatch result hit=%s score=%s box=%s", result.hit, result.score, result.box)
        if not result.hit:
            exit_code = 7
    except (ControllerConnectionError, TaskRuntimeError, ScreenshotError, TemplateMatchDiagnosticError) as error:
        print(f"TemplateMatch diagnostic failed: {error}", file=sys.stderr)
        logger.exception("TemplateMatch diagnostic failed")
        exit_code = 7
    finally:
        if session is not None:
            try:
                session.close()
                print("Win32 controller deactivated successfully.")
            except ControllerConnectionError as error:
                print(f"Controller cleanup failed: {error}", file=sys.stderr)
                exit_code = 4
    return exit_code


def run_input_test_program(args) -> int:
    config = _load_cli_config(args.config)
    workspace = create_debug_workspace(PROJECT_ROOT, config["diagnostics"]["debug_dir"])
    log_path = configure_file_logging(workspace)
    logger = logging.getLogger(__name__)
    print(f"Debug log: {log_path}")
    print(f"MaaFramework: {get_maa_version()}")

    try:
        window = choose_window_for_run(
            args.title,
            args.class_name,
            args.visible_only,
            args.index,
        )
    except WindowSelectionError as error:
        print(f"Window selection failed: {error}", file=sys.stderr)
        return 2

    point = tuple(args.point)
    print(f"Selected: 0x{window.hwnd:X} {window.class_name} {window.title}")
    print(f"Planned double-click: {point} (2 clicks, 100ms interval)")
    print("Mouse input: Seize (the target window and physical mouse may be occupied briefly)")
    if not args.yes:
        print(
            "Type YES to perform this double-click (the target may open): ",
            end="",
            file=sys.stderr,
            flush=True,
        )
        if _read_stdin_line() != "YES":
            print("Input test cancelled; no click was sent.")
            return 0

    session = None
    exit_code = 0
    try:
        session = AutomationSession.connect(
            window,
            config,
            PROJECT_ROOT,
            workspace,
            mouse_input="Seize",
        )
        controller = session.controller
        timestamp_prefix = "input-test"
        before_path = workspace.timestamped_path(workspace.screenshots, f"{timestamp_prefix}-before", ".png")
        after_path = workspace.timestamped_path(workspace.screenshots, f"{timestamp_prefix}-after", ".png")
        difference_path = workspace.timestamped_path(
            workspace.screenshots, f"{timestamp_prefix}-difference", ".png"
        )
        report_path = workspace.timestamped_path(workspace.reports, timestamp_prefix, ".json")
        result = run_input_test(
            controller,
            point,
            before_path,
            after_path,
            difference_path,
            report_path,
        )
        print(f"Double-click succeeded at: {result.point} ({result.click_count} click jobs)")
        print(f"Controller input point: {result.input_point}")
        print(f"Visual change detected: {result.difference.visual_change_detected}")
        print(f"Changed pixel ratio: {result.difference.changed_pixel_ratio:.6f}")
        print(f"Mean absolute difference: {result.difference.mean_absolute_difference:.6f}")
        print(f"Before: {result.before_path}")
        print(f"After: {result.after_path}")
        print(f"Difference: {result.difference_path}")
        print(f"Report: {result.report_path}")
        logger.info("Input test point=%s difference=%s", point, result.difference)
        if not result.difference.visual_change_detected:
            exit_code = 8
    except (ControllerConnectionError, ScreenshotError, InputTestError) as error:
        print(f"Input test failed: {error}", file=sys.stderr)
        logger.exception("Input test failed")
        exit_code = 8
    finally:
        if session is not None:
            try:
                session.close()
                print("Win32 controller deactivated successfully.")
            except ControllerConnectionError as error:
                print(f"Controller cleanup failed: {error}", file=sys.stderr)
                exit_code = 4
    return exit_code


def run_template_action_program(args) -> int:
    config = _load_cli_config(args.config)
    workspace = create_debug_workspace(PROJECT_ROOT, config["diagnostics"]["debug_dir"])
    log_path = configure_file_logging(workspace)
    logger = logging.getLogger(__name__)
    print(f"Debug log: {log_path}")
    print(f"MaaFramework: {get_maa_version()}")

    try:
        window = choose_window_for_run(
            args.title,
            args.class_name,
            args.visible_only,
            args.index,
        )
    except WindowSelectionError as error:
        print(f"Window selection failed: {error}", file=sys.stderr)
        return 2

    source_description = str(args.template) if args.template else f"live ROI {args.template_roi}"
    print(f"Selected: 0x{window.hwnd:X} {window.class_name} {window.title}")
    print(f"Template source: {source_description}")
    print(f"Planned action: {args.action} at the recognized box center")
    print("Mouse input: Seize (the target window and physical mouse may be occupied briefly)")
    if not args.yes:
        print("Type YES to perform this action: ", end="", file=sys.stderr, flush=True)
        if _read_stdin_line() != "YES":
            print("Template action cancelled; no input was sent.")
            return 0

    session = None
    exit_code = 0
    try:
        session = AutomationSession.connect(
            window,
            config,
            PROJECT_ROOT,
            workspace,
            mouse_input="Seize",
        )
        controller = session.controller
        runtime = session.initialize_runtime()

        if args.template is not None:
            template_path = args.template
            if not template_path.is_absolute():
                template_path = PROJECT_ROOT / template_path
            template = load_template_image(template_path.resolve())
        else:
            template = crop_template(capture_image(controller), tuple(args.template_roi))

        prefix = "template-action"
        result = run_template_action(
            runtime,
            controller,
            template,
            args.threshold,
            args.action,
            workspace.timestamped_path(workspace.screenshots, f"{prefix}-before", ".png"),
            workspace.timestamped_path(workspace.screenshots, f"{prefix}-after", ".png"),
            workspace.timestamped_path(workspace.screenshots, f"{prefix}-target", ".png"),
            workspace.timestamped_path(workspace.screenshots, f"{prefix}-difference", ".png"),
            workspace.timestamped_path(workspace.reports, prefix, ".json"),
        )
        print(f"TemplateMatch score: {result.score}")
        print(f"Matched box: {result.box}")
        print(f"Action point: {result.point}")
        print(f"Controller input point: {result.input_point}")
        print(f"Action succeeded: {result.action} ({result.click_count} click jobs)")
        print(f"Visual change detected: {result.difference.visual_change_detected}")
        print(f"Changed pixel ratio: {result.difference.changed_pixel_ratio:.6f}")
        print(f"Target image: {result.annotated_path}")
        print(f"Before: {result.before_path}")
        print(f"After: {result.after_path}")
        print(f"Difference: {result.difference_path}")
        print(f"Report: {result.report_path}")
        logger.info(
            "Template action=%s point=%s score=%s difference=%s",
            result.action,
            result.point,
            result.score,
            result.difference,
        )
        if not result.difference.visual_change_detected:
            exit_code = 9
    except (
        ControllerConnectionError,
        ScreenshotError,
        TaskRuntimeError,
        TemplateMatchDiagnosticError,
        TemplateActionError,
    ) as error:
        print(f"Template action failed: {error}", file=sys.stderr)
        logger.exception("Template action failed")
        exit_code = 9
    finally:
        if session is not None:
            try:
                session.close()
                print("Win32 controller deactivated successfully.")
            except ControllerConnectionError as error:
                print(f"Controller cleanup failed: {error}", file=sys.stderr)
                exit_code = 4
    return exit_code


def run_workflow_program(args) -> int:
    config = _load_cli_config(args.config)
    workspace = create_debug_workspace(PROJECT_ROOT, config["diagnostics"]["debug_dir"])
    log_path = configure_file_logging(workspace)
    logger = logging.getLogger(__name__)
    workflow_path = resolve_workflow_path(args.workflow)
    try:
        definition = load_workflow(workflow_path.resolve(), PROJECT_ROOT)
    except WorkflowConfigError as error:
        print(f"Workflow configuration failed: {error}", file=sys.stderr)
        return 10

    print(f"Debug log: {log_path}")
    print(f"MaaFramework: {get_maa_version()}")
    print(f"Workflow: {definition.name} ({len(definition.steps)} step(s))")
    for index, step in enumerate(definition.steps, start=1):
        print(
            f"  {index}. {step.name}: {step.action}, template={step.template_path}, "
            f"attempts={step.recognition_attempts}"
        )

    try:
        window = choose_window_for_run(
            args.title,
            args.class_name,
            args.visible_only,
            args.index,
        )
    except WindowSelectionError as error:
        print(f"Window selection failed: {error}", file=sys.stderr)
        return 2

    print(f"Selected: 0x{window.hwnd:X} {window.class_name} {window.title}")
    print("Mouse input: Seize (the target window and physical mouse may be occupied briefly)")
    if not args.yes:
        print("Type YES to perform this workflow: ", end="", file=sys.stderr, flush=True)
        if _read_stdin_line() != "YES":
            print("Workflow cancelled; no input was sent.")
            return 0

    session = None
    exit_code = 0
    try:
        session = AutomationSession.connect(
            window,
            config,
            PROJECT_ROOT,
            workspace,
            mouse_input="Seize",
        )
        controller = session.controller
        runtime = session.initialize_runtime()
        result = run_workflow(definition, runtime, controller, workspace)

        for index, step_result in enumerate(result.steps, start=1):
            action_result = step_result.action_result
            print(
                f"Step {index} succeeded: {step_result.name}; action={action_result.action}; "
                f"point={action_result.point}; score={action_result.score}; "
                f"recognition_attempt={step_result.recognition_attempt}"
            )
        print(f"Workflow succeeded: {result.name}")
        print(f"Workflow report: {result.report_path}")
        logger.info("Workflow succeeded name=%r steps=%s", result.name, len(result.steps))
    except (
        ControllerConnectionError,
        TaskRuntimeError,
        TemplateActionError,
        WorkflowExecutionError,
    ) as error:
        print(f"Workflow failed: {error}", file=sys.stderr)
        logger.exception("Workflow failed")
        exit_code = 10
    finally:
        if session is not None:
            try:
                session.close()
                print("Win32 controller deactivated successfully.")
            except ControllerConnectionError as error:
                print(f"Controller cleanup failed: {error}", file=sys.stderr)
                exit_code = 4
    return exit_code


def run_workflow_v2_program(args) -> int:
    config = _load_cli_config(args.config)
    workspace = create_debug_workspace(PROJECT_ROOT, config["diagnostics"]["debug_dir"])
    log_path = configure_file_logging(workspace)
    logger = logging.getLogger(__name__)
    workflow_path = resolve_workflow_path(args.workflow)
    try:
        definition = load_workflow_v2(workflow_path.resolve(), PROJECT_ROOT)
    except WorkflowV2ConfigError as error:
        print(f"Workflow v2 configuration failed: {error}", file=sys.stderr)
        return 11

    target = definition.target
    title_filter = args.title or (target.title_pattern if target else None)
    class_filter = args.class_name or (target.class_name if target else None)
    profile = get_input_profile(args.input_profile)
    print(f"Debug log: {log_path}")
    print(f"MaaFramework: {get_maa_version()}")
    print(f"Workflow v2: {definition.name} ({len(definition.steps)} step(s))")
    print(
        f"Input profile: {profile.name.value}; mouse={profile.mouse_method}; "
        f"keyboard={profile.keyboard_method}"
    )
    print(f"Input warning: {profile.warning}")

    try:
        window = choose_window_for_run(
            title_filter,
            class_filter,
            args.visible_only,
            args.index,
        )
    except WindowSelectionError as error:
        print(f"Window selection failed: {error}", file=sys.stderr)
        return 2

    print(f"Selected: 0x{window.hwnd:X} {window.class_name} {window.title}")
    if not args.yes:
        print("Type YES to perform this workflow: ", end="", file=sys.stderr, flush=True)
        if _read_stdin_line() != "YES":
            print("Workflow cancelled; no input was sent.")
            return 0

    def report_event(event) -> None:
        if event.type in {
            WorkflowEventType.STEP_STARTED,
            WorkflowEventType.STEP_SUCCEEDED,
            WorkflowEventType.STEP_FAILED,
            WorkflowEventType.STEP_SKIPPED,
        }:
            print(f"{event.type.value}: {event.step_id} {event.step_name or ''}".rstrip())

    session = None
    exit_code = 0
    try:
        session = AutomationSession.connect(
            window,
            config,
            PROJECT_ROOT,
            workspace,
            mouse_input=profile.mouse_method,
            keyboard_input=profile.keyboard_method,
            mouse_lock_follow=profile.mouse_lock_follow,
            direct_screen_input=profile.direct_screen_input,
        )
        result = WorkflowEngine(report_event).run(definition, session)
        failed_steps = [step for step in result.steps if not step.succeeded]
        if result.cancelled:
            print("Workflow v2 cancelled.")
        elif failed_steps:
            failed_names = ", ".join(step.step_id for step in failed_steps)
            print(
                f"Workflow v2 finished with {len(failed_steps)} failed "
                f"step(s): {failed_names}",
                file=sys.stderr,
            )
            exit_code = 11
        else:
            print(f"Workflow v2 succeeded: {result.workflow_name}")
        logger.info(
            "Workflow v2 finished name=%r steps=%s cancelled=%s",
            result.workflow_name,
            len(result.steps),
            result.cancelled,
        )
    except (
        ControllerConnectionError,
        ScreenshotError,
        TaskRuntimeError,
        TemplateActionError,
        WorkflowV2ExecutionError,
    ) as error:
        print(f"Workflow v2 failed: {error}", file=sys.stderr)
        logger.exception("Workflow v2 failed")
        exit_code = 11
    finally:
        if session is not None:
            try:
                session.close()
                print("Win32 controller deactivated successfully.")
            except ControllerConnectionError as error:
                print(f"Controller cleanup failed: {error}", file=sys.stderr)
                exit_code = 4
    return exit_code


def run_window_select(config_path: Path, as_json: bool) -> int:
    config = _load_cli_config(config_path)
    window_config = config["window"]
    try:
        window = select_target_window(
            title_filter=window_config["title_pattern"],
            class_filter=window_config["class_name"],
        )
    except WindowSelectionError as error:
        print(f"Window selection failed: {error}", file=sys.stderr)
        return 2

    if as_json:
        print(json.dumps(window.to_dict(), ensure_ascii=False, indent=2))
    else:
        print(f"Selected HWND: 0x{window.hwnd:X}")
        print(f"Title: {window.title}")
        print(f"Class: {window.class_name}")
        print(f"Window size: {window.window_width}x{window.window_height}")
        print(f"Client size: {window.client_width}x{window.client_height}")
        print(f"Visible: {window.visible}")
        print(f"Minimized: {window.minimized}")
        print("Selection was read-only. No controller was created and no input was sent.")
    return 0


def run_self_test(config_path: Path) -> int:
    config = _load_cli_config(config_path)
    required_directories = (
        PROJECT_ROOT / "assets" / "resource" / "pipeline",
        PROJECT_ROOT / "assets" / "resource" / "image",
    )
    missing = [path for path in required_directories if not path.is_dir()]
    if missing:
        for path in missing:
            print(f"Missing required directory: {path}")
        return 1

    workspace = create_debug_workspace(PROJECT_ROOT, config["diagnostics"]["debug_dir"])

    print("Framework self-test passed.")
    print(f"Configuration: {config_path.resolve()}")
    print(f"Capture preference: {config['controller']['screencap_mode']}")
    print(f"MaaFramework: {get_maa_version()}")
    print(f"Debug workspace: {workspace.root}")
    print("No window was searched and no input was sent.")
    return 0


def main(argv: list[str] | None = None) -> int:
    configure_console()
    args = build_parser().parse_args(argv)
    try:
        return _dispatch(args)
    except CliConfigError as error:
        print(str(error), file=sys.stderr)
        return 1


def _dispatch(args) -> int:
    if args.command == "self-test":
        return run_self_test(args.config)
    if args.command == "maa-version":
        print(get_maa_version())
        return 0
    if args.command == "run":
        return run_program(
            args.config,
            args.title,
            args.class_name,
            args.visible_only,
            args.index,
        )
    if args.command == "capture":
        return run_program(
            args.config,
            args.title,
            args.class_name,
            args.visible_only,
            args.index,
            capture_requested=True,
        )
    if args.command == "template-match":
        return run_template_match_program(args)
    if args.command == "input-test":
        return run_input_test_program(args)
    if args.command == "template-action":
        return run_template_action_program(args)
    if args.command == "workflow-run":
        return run_workflow_program(args)
    if args.command == "workflow-run-v2":
        return run_workflow_v2_program(args)
    if args.command == "windows" and args.windows_command == "list":
        return run_window_list(args.title, args.class_name, args.json)
    if args.command == "windows" and args.windows_command == "select":
        return run_window_select(args.config, args.json)
    if args.command == "windows" and args.windows_command == "choose":
        return run_window_choose(
            args.title,
            args.class_name,
            args.visible_only,
            args.index,
            args.json,
        )
    return 1
