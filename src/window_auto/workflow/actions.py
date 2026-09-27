"""Execute individual workflow v2 steps against MaaFramework."""

from __future__ import annotations

from dataclasses import dataclass
import random

from window_auto.automation.template_action import box_center, load_template_image
from window_auto.diagnostics.screenshot import capture_image
from window_auto.diagnostics.desktop_scope import (
    DesktopCoordinateError,
    DesktopRecognitionFrame,
    capture_desktop_recognition_frame,
    desktop_box_to_controller,
    scale_box_between_sizes,
)
from window_auto.diagnostics.template_match import MatchBox, recognize_template
from window_auto.diagnostics.ocr_match import recognize_ocr
from window_auto.runtime.humanize import (
    curve_points,
    humanize_from_config,
    jitter_duration_ms,
    jitter_point,
    uniform_seconds,
)
from window_auto.runtime.win32_input import DirectInputError, click_client_point
from window_auto.workflow.context import ExecutionContext
from window_auto.workflow.model import (
    KeyPressStep,
    MouseClickStep,
    MouseMoveStep,
    OcrMatchStep,
    TemplateMatchStep,
    TextInputStep,
    WaitStep,
    WorkflowStep,
)
from window_auto.workflow.virtual_keys import resolve_text_character, resolve_virtual_key


# SystemRandom draws from the OS entropy source, so random wait durations
# cannot be predicted or reproduced from a seeded pseudo-random sequence.
_WAIT_RANDOM = random.SystemRandom()


class WorkflowActionError(RuntimeError):
    """Raised when one workflow action fails."""


class TemplateNotFoundError(WorkflowActionError):
    """Raised when all configured template recognition attempts miss."""


@dataclass(frozen=True, slots=True)
class ActionResult:
    output: object | None = None


def _successful(job, description: str) -> None:
    completed = job.wait()
    if not completed.succeeded:
        raise WorkflowActionError(
            f"MaaFramework 操作失败：{description}。"
            "请确认目标窗口仍在前台且未最小化，必要时更换输入策略后重试。"
        )


def _humanize(context: ExecutionContext):
    session_config = getattr(context.session, "config", None)
    if not isinstance(session_config, dict):
        session_config = {}
    return humanize_from_config(session_config)


def _jittered_interval_ms(base_ms: int, context: ExecutionContext) -> int:
    return jitter_duration_ms(base_ms, _humanize(context).timing_jitter_ratio)


def _move_pointer_along_curve(
    context: ExecutionContext,
    target: tuple[int, int],
) -> None:
    """Glide the pointer from its last known position toward ``target``."""
    start = context.pointer
    if start is None or tuple(start) == tuple(target):
        return
    for x, y in curve_points(tuple(start), tuple(target))[:-1]:
        context.cancellation.check()
        _successful(
            context.session.controller.post_touch_move(x, y),
            f"mouse move to {(x, y)}",
        )
        context.cancellation.wait(uniform_seconds(0.004, 0.012))


def _click(
    context: ExecutionContext,
    point: tuple[int, int],
    button: str,
    description: str,
) -> tuple[int, int]:
    session_config = getattr(context.session, "config", {})
    controller_config = session_config.get("controller", {})
    humanize = _humanize(context)
    if humanize.click_jitter_px:
        point = jitter_point((int(point[0]), int(point[1])), humanize.click_jitter_px)
    point = (int(point[0]), int(point[1]))
    if controller_config.get("direct_screen_input", False):
        window = context.session.window
        if window is None:
            raise WorkflowActionError(
                "前台精确输入需要先选择目标窗口，请先点击“选择窗口”。"
            )
        direct_options: dict[str, object] = {}
        if humanize.enabled:
            direct_options["hold_seconds"] = uniform_seconds(0.04, 0.12)
            direct_options["move_curve"] = humanize.mouse_curve
        try:
            click_client_point(window, point, button, **direct_options)
        except DirectInputError as error:
            raise WorkflowActionError(str(error)) from error
        context.pointer = point
        return point
    if humanize.mouse_curve:
        _move_pointer_along_curve(context, point)
    contact = {"left": 0, "right": 1, "middle": 2}[button]
    _successful(
        context.session.controller.post_click(point[0], point[1], contact=contact),
        description,
    )
    context.pointer = point
    return point


def _match_point(context: ExecutionContext, variable: str) -> tuple[int, int]:
    value = context.variables.get(variable)
    if not isinstance(value, MatchBox):
        raise WorkflowActionError(
            f"识别结果变量 {variable!r} 不存在或不是有效的识别框。"
            f"请先添加并成功执行结果变量为 {variable!r} 的模板识别步骤。"
        )
    return box_center(value)


def _capture_scope(context: ExecutionContext) -> str:
    controller_config = getattr(context.session, "config", {}).get("controller", {})
    return str(controller_config.get("capture_scope", "window"))


def _recognition_frame(
    context: ExecutionContext,
) -> tuple[object, DesktopRecognitionFrame | None]:
    if _capture_scope(context) != "desktop":
        return capture_image(context.session.controller), None
    long_side = context.session.config["controller"]["screenshot_target_long_side"]
    frame = capture_desktop_recognition_frame(long_side)
    return frame.image, frame


def _controller_box(
    box: MatchBox,
    context: ExecutionContext,
    frame: DesktopRecognitionFrame | None,
    recognition_size: tuple[int, int],
) -> MatchBox:
    controller_input_size = getattr(
        context.session,
        "controller_raw_size",
        None,
    )
    if controller_input_size is None:
        controller_input_size = tuple(context.session.controller.resolution)
    if (
        len(controller_input_size) != 2
        or controller_input_size[0] <= 0
        or controller_input_size[1] <= 0
    ):
        raise WorkflowActionError(
            f"控制器输入分辨率无效：{controller_input_size!r}。"
            "请重新选择目标窗口后重试。"
        )
    if frame is None:
        try:
            return scale_box_between_sizes(
                box,
                recognition_size,
                controller_input_size,
            )
        except DesktopCoordinateError as error:
            raise WorkflowActionError(str(error)) from error
    window = context.session.window
    if (
        window is None
        or window.client_x is None
        or window.client_y is None
        or window.client_width is None
        or window.client_height is None
    ):
        raise WorkflowActionError(
            "桌面截图范围需要目标窗口的客户区位置和尺寸，请重新选择目标窗口后重试。"
        )
    try:
        return desktop_box_to_controller(
            box,
            frame,
            (window.client_x, window.client_y),
            (window.client_width, window.client_height),
            controller_input_size,
        )
    except DesktopCoordinateError as error:
        raise WorkflowActionError(str(error)) from error


def _run_template_match(
    step: TemplateMatchStep,
    context: ExecutionContext,
) -> ActionResult:
    if step.attempts < 1:
        raise WorkflowActionError(
            f"模板识别次数至少为 1，当前为 {step.attempts}。请在步骤属性中修正。"
        )
    runtime = context.session.initialize_runtime()
    template = load_template_image(step.template_path)
    for attempt in range(1, step.attempts + 1):
        context.cancellation.check()
        image, desktop_frame = _recognition_frame(context)
        recognition = recognize_template(
            runtime,
            image,
            template,
            step.threshold,
        )
        if recognition.hit and recognition.box is not None:
            image_height, image_width = image.shape[:2]
            controller_box = _controller_box(
                recognition.box,
                context,
                desktop_frame,
                (image_width, image_height),
            )
            context.variables[step.result_variable] = controller_box
            point = box_center(controller_box)
            post_action_output = _run_template_post_action(
                step,
                context,
                point,
            )
            return ActionResult(
                {
                    "attempt": attempt,
                    "score": recognition.score,
                    "box": recognition.box,
                    "controller_box": controller_box,
                    "point": point,
                    "variable": step.result_variable,
                    "post_action": post_action_output,
                }
            )
        if attempt < step.attempts:
            context.cancellation.wait(step.interval_ms / 1000.0)
    candidate_detail = ""
    if recognition.candidate_score is not None and recognition.candidate_box is not None:
        box = recognition.candidate_box
        candidate_detail = (
            f"最接近的候选得分 {recognition.candidate_score:.3f}"
            f"（位置 [{box.x},{box.y},{box.w},{box.h}]），"
            f"低于识别阈值 {step.threshold:.3f}，可适当降低阈值或重新截取模板。"
        )
    raise TemplateNotFoundError(
        f"识别 {step.attempts} 次后仍未找到模板：{step.template_path}。"
        "请确认目标画面已显示。"
        f"{candidate_detail}"
    )


def _run_ocr_match(
    step: OcrMatchStep,
    context: ExecutionContext,
) -> ActionResult:
    if step.attempts < 1:
        raise WorkflowActionError(
            f"OCR 识别次数至少为 1，当前为 {step.attempts}。请在步骤属性中修正。"
        )
    if not step.expected:
        raise WorkflowActionError(
            "OCR 识别缺少期望文本，请在步骤属性中填写要查找的文字。"
        )
    runtime = context.session.initialize_runtime()
    for attempt in range(1, step.attempts + 1):
        context.cancellation.check()
        image, desktop_frame = _recognition_frame(context)
        recognition = recognize_ocr(
            runtime,
            image,
            step.expected,
            step.threshold,
        )
        if recognition.hit and recognition.box is not None:
            image_height, image_width = image.shape[:2]
            controller_box = _controller_box(
                recognition.box,
                context,
                desktop_frame,
                (image_width, image_height),
            )
            context.variables[step.result_variable] = controller_box
            point = box_center(controller_box)
            post_action_output = _run_template_post_action(
                step,
                context,
                point,
            )
            return ActionResult(
                {
                    "attempt": attempt,
                    "score": recognition.score,
                    "text": recognition.text,
                    "box": recognition.box,
                    "controller_box": controller_box,
                    "point": point,
                    "variable": step.result_variable,
                    "post_action": post_action_output,
                }
            )
        if attempt < step.attempts:
            context.cancellation.wait(step.interval_ms / 1000.0)
    expected_detail = "、".join(f"“{item}”" for item in step.expected)
    raise TemplateNotFoundError(
        f"OCR 识别 {step.attempts} 次后仍未找到文字：{expected_detail}。"
        "请确认目标画面已显示，必要时可适当降低识别阈值。"
    )


def _press_key(
    key_value: str | int,
    modifier_values: tuple[str | int, ...],
    hold_ms: int,
    context: ExecutionContext,
) -> dict[str, object]:
    controller = context.session.controller
    key = resolve_virtual_key(key_value)
    modifiers = [resolve_virtual_key(value) for value in modifier_values]
    hold_ms = jitter_duration_ms(hold_ms, _humanize(context).timing_jitter_ratio)
    pressed: list[int] = []
    primary_error: BaseException | None = None
    try:
        for modifier in modifiers:
            _successful(controller.post_key_down(modifier), f"key down {modifier}")
            pressed.append(modifier)
        _successful(controller.post_key_down(key), f"key down {key}")
        pressed.append(key)
        context.cancellation.wait(hold_ms / 1000.0)
    except BaseException as error:
        primary_error = error
        raise
    finally:
        cleanup_errors: list[WorkflowActionError] = []
        for modifier in reversed(pressed):
            try:
                _successful(controller.post_key_up(modifier), f"key up {modifier}")
            except WorkflowActionError as cleanup_error:
                cleanup_errors.append(cleanup_error)
        if cleanup_errors:
            if primary_error is None:
                raise cleanup_errors[0]
            for cleanup_error in cleanup_errors:
                primary_error.add_note(str(cleanup_error))
    return {"keycode": key, "modifiers": modifiers, "hold_ms": hold_ms}


def _run_key_press(step: KeyPressStep, context: ExecutionContext) -> ActionResult:
    return ActionResult(
        _press_key(
            step.key,
            step.modifiers,
            step.hold_ms,
            context,
        )
    )


def _run_template_post_action(
    step: TemplateMatchStep | OcrMatchStep,
    context: ExecutionContext,
    point: tuple[int, int],
) -> dict[str, object]:
    if step.post_action == "none":
        return {"action": "none"}
    if step.post_action == "key_press":
        return {
            "action": "key_press",
            **_press_key(
                step.post_key,
                step.post_modifiers,
                step.post_key_hold_ms,
                context,
            ),
        }

    count = 2 if step.post_action == "double_click" else 1
    target = point
    for click_index in range(count):
        point = _click(
            context,
            target,
            step.post_button,
            f"{step.post_button} post-recognition click at {target}",
        )
        if click_index + 1 < count:
            context.cancellation.wait(
                _jittered_interval_ms(step.post_action_interval_ms, context) / 1000.0
            )
    return {
        "action": step.post_action,
        "point": point,
        "button": step.post_button,
        "count": count,
    }


def _run_text_input(step: TextInputStep, context: ExecutionContext) -> ActionResult:
    controller = context.session.controller
    if step.strategy == "direct":
        _successful(controller.post_input_text(step.text), "direct text input")
    else:
        for character in step.text:
            context.cancellation.check()
            try:
                key, shift_required = resolve_text_character(character)
            except ValueError as error:
                raise WorkflowActionError(str(error)) from error
            if shift_required:
                _successful(controller.post_key_down(0x10), "text shift down")
            try:
                _successful(controller.post_key_down(key), f"text character down {character!r}")
                _successful(controller.post_key_up(key), f"text character up {character!r}")
            finally:
                if shift_required:
                    _successful(controller.post_key_up(0x10), "text shift up")
            interval_ms = _jittered_interval_ms(step.interval_ms, context)
            if interval_ms:
                context.cancellation.wait(interval_ms / 1000.0)
    return ActionResult(
        {
            "length": len(step.text),
            "strategy": step.strategy,
            "text": None if step.sensitive else step.text,
        }
    )


def execute_action(step: WorkflowStep, context: ExecutionContext) -> ActionResult:
    context.cancellation.check()
    controller = context.session.controller

    if isinstance(step, WaitStep):
        duration_ms = (
            _WAIT_RANDOM.randint(step.min_duration_ms, step.max_duration_ms)
            if step.delay_mode == "random"
            else step.duration_ms
        )
        context.cancellation.wait(duration_ms / 1000.0)
        return ActionResult(
            {
                "delay_mode": step.delay_mode,
                "duration_ms": duration_ms,
            }
        )
    if isinstance(step, MouseMoveStep):
        if step.move_mode == "relative":
            _successful(
                controller.post_relative_move(step.delta_x, step.delta_y),
                f"relative mouse move by {(step.delta_x, step.delta_y)}",
            )
            if context.pointer is not None:
                context.pointer = (
                    context.pointer[0] + step.delta_x,
                    context.pointer[1] + step.delta_y,
                )
            return ActionResult(
                {
                    "move_mode": "relative",
                    "delta": (step.delta_x, step.delta_y),
                }
            )
        target = (int(step.x), int(step.y))
        humanize = _humanize(context)
        if (
            humanize.mouse_curve
            and context.pointer is not None
            and tuple(context.pointer) != target
        ):
            for x, y in curve_points(tuple(context.pointer), target):
                context.cancellation.check()
                _successful(
                    controller.post_touch_move(x, y),
                    f"mouse move to {(x, y)}",
                )
                if (x, y) != target:
                    context.cancellation.wait(uniform_seconds(0.004, 0.012))
        else:
            _successful(
                controller.post_touch_move(step.x, step.y),
                f"mouse move to {(step.x, step.y)}",
            )
        context.pointer = target
        return ActionResult(
            {
                "move_mode": "absolute",
                "point": target,
            }
        )
    if isinstance(step, MouseClickStep):
        point = (
            _match_point(context, step.match_variable)
            if step.match_variable is not None
            else (step.x, step.y)
        )
        if point[0] is None or point[1] is None:
            raise WorkflowActionError(
                "鼠标点击步骤缺少坐标或识别结果变量，请在步骤属性中补全后再运行。"
            )
        base_point = (int(point[0]), int(point[1]))
        for click_index in range(step.count):
            point = _click(
                context,
                base_point,
                step.button,
                f"{step.button} click at {base_point}",
            )
            if click_index + 1 < step.count:
                context.cancellation.wait(
                    _jittered_interval_ms(step.interval_ms, context) / 1000.0
                )
        return ActionResult({"point": point, "button": step.button, "count": step.count})
    if isinstance(step, KeyPressStep):
        return _run_key_press(step, context)
    if isinstance(step, TextInputStep):
        return _run_text_input(step, context)
    if isinstance(step, TemplateMatchStep):
        return _run_template_match(step, context)
    if isinstance(step, OcrMatchStep):
        return _run_ocr_match(step, context)
    raise WorkflowActionError(f"不支持的步骤类型：{type(step).__name__}。")
