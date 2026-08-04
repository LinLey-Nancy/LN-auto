"""Dynamic property form for one workflow step."""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)


FIELD_LABELS = {
    "id": "步骤 ID",
    "type": "动作类型",
    "name": "显示名称",
    "enabled": "启用",
    "on_failure": "失败时",
    "template": "模板路径",
    "threshold": "识别阈值",
    "attempts": "识别次数",
    "result_variable": "结果变量",
    "post_action": "识别后操作",
    "post_button": "操作鼠标按键",
    "post_action_interval_ms": "双击间隔（毫秒）",
    "post_key": "操作按键",
    "post_modifiers": "操作组合键",
    "post_key_hold_ms": "操作按键持续（毫秒）",
    "move_mode": "移动方式",
    "x": "X 坐标",
    "y": "Y 坐标",
    "delta_x": "X 移动距离",
    "delta_y": "Y 移动距离",
    "match_variable": "匹配变量",
    "button": "鼠标按键",
    "count": "点击次数",
    "key": "按键",
    "modifiers": "组合键",
    "hold_ms": "按下持续（毫秒）",
    "text": "输入文本",
    "strategy": "文本策略",
    "interval_ms": "间隔（毫秒）",
    "delay_mode": "延迟方式",
    "duration_ms": "固定延迟（毫秒）",
    "min_duration_ms": "最短延迟（毫秒）",
    "max_duration_ms": "最长延迟（毫秒）",
    "sensitive": "敏感内容",
}

FIELD_HELP = {
    "id": (
        "步骤的唯一标识。只能使用字母、数字、连字符和下划线；"
        "同一个工作流内不能重复。"
    ),
    "type": "当前步骤执行的动作类型。创建步骤后不可直接修改。",
    "name": "显示在步骤列表和运行日志中的名称，用来帮助你辨认这个步骤。",
    "enabled": "关闭后运行工作流时会跳过这个步骤，但仍保留其配置。",
    "on_failure": (
        "步骤执行失败后的处理方式。“停止工作流”会立即结束；"
        "“继续下一步”会忽略本次失败；模板识别还可选择“再次运行”，"
        "持续重新识别，直到成功或用户停止工作流。"
    ),
    "template": (
        "用于画面匹配的 PNG/JPG 图片路径。建议使用右侧按钮选择已有图片，"
        "或从截图框选创建模板。项目内路径会保存为相对路径。"
    ),
    "threshold": (
        "模板识别的最低相似度，范围为 0～1。数值越高越严格；"
        "0.8 表示相似度达到 80% 才算识别成功。"
    ),
    "attempts": (
        "每次运行该步骤时最多连续识别的次数。每次失败会等待“间隔”后重试；"
        "若失败策略为“再次运行”，次数用完后会开启下一轮。"
    ),
    "result_variable": (
        "保存识别结果的位置名称。后续鼠标点击步骤可以通过“匹配变量”"
        "读取该结果并点击识别区域中心。"
    ),
    "post_action": (
        "模板识别成功后立即执行的操作。可以不操作、点击匹配区域中心、"
        "双击匹配区域中心，或发送一个键盘按键。"
    ),
    "post_button": "识别成功后点击匹配区域中心时使用的鼠标按键。",
    "post_action_interval_ms": "识别成功后执行双击时，两次点击之间的等待时间。",
    "post_key": "模板识别成功后要发送的键名或 Windows 虚拟键码。",
    "post_modifiers": "识别后按键使用的组合键，多个按键用英文逗号分隔。",
    "post_key_hold_ms": "识别后按键从按下到抬起之间保持的时间。",
    "move_mode": (
        "“绝对位置”移动到目标窗口原始客户区的指定坐标；"
        "“相对距离”从当前鼠标位置按 X/Y 距离移动。"
    ),
    "x": "目标窗口原始客户区的横坐标，坐标原点位于客户区左上角。",
    "y": "目标窗口原始客户区的纵坐标，坐标原点位于客户区左上角。",
    "delta_x": "相对移动的水平距离。正数向右，负数向左。",
    "delta_y": "相对移动的垂直距离。正数向下，负数向上。",
    "match_variable": "读取模板识别步骤保存的结果变量，并使用匹配区域中心作为位置。",
    "button": "要发送的鼠标按键。",
    "count": "点击次数；1 为单击，2 为双击。",
    "key": "要发送的键名或 Windows 虚拟键码，例如 ENTER、F1 或 65。",
    "modifiers": "组合键列表，多个按键用英文逗号分隔，例如 CTRL, SHIFT。",
    "hold_ms": "键盘按键从按下到抬起之间保持的时间，单位为毫秒。",
    "text": "需要输入到目标窗口的文本内容。",
    "strategy": "逐键输入兼容性更好；Maa 直接文本适用于支持文本注入的窗口。",
    "interval_ms": "相邻两次识别、点击或按键之间等待的毫秒数，具体含义取决于动作类型。",
    "delay_mode": "选择固定延迟，或在指定最短值和最长值之间生成随机延迟。",
    "duration_ms": "固定延迟模式下暂停工作流的时长。",
    "min_duration_ms": "随机延迟可能产生的最短时间，必须小于或等于最长延迟。",
    "max_duration_ms": "随机延迟可能产生的最长时间，必须大于或等于最短延迟。",
    "sensitive": "开启后，运行结果不会回显输入文本，适合密码或其他敏感内容。",
}

CHOICES = {
    "on_failure": (("停止工作流", "stop"), ("继续下一步", "continue")),
    "button": (("左键", "left"), ("右键", "right"), ("中键", "middle")),
    "post_button": (("左键", "left"), ("右键", "right"), ("中键", "middle")),
    "post_action": (
        ("不执行操作", "none"),
        ("单击识别位置", "click"),
        ("双击识别位置", "double_click"),
        ("键盘按键", "key_press"),
    ),
    "delay_mode": (("固定延迟", "fixed"), ("随机延迟", "random")),
    "move_mode": (("绝对位置", "absolute"), ("相对距离", "relative")),
    "strategy": (("逐键输入（兼容性优先）", "key_sequence"), ("Maa 直接文本", "direct")),
}


class PropertyEditor(QWidget):
    property_changed = Signal(int, str, object)
    template_select_requested = Signal(int)
    template_create_requested = Signal(int)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._step_index = -1
        self._step_type = ""
        self._step: dict[str, Any] | None = None
        self._form_host = QWidget()
        self._form = QFormLayout(self._form_host)
        self._form.setContentsMargins(12, 12, 12, 12)
        self._form.setHorizontalSpacing(14)
        self._form.setVerticalSpacing(10)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll.setWidget(self._form_host)

        title = QLabel("步骤属性")
        title.setObjectName("sectionTitle")
        self._empty = QLabel("选择一个步骤以编辑参数。")
        self._empty.setObjectName("mutedLabel")
        self._empty.setWordWrap(True)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.addWidget(title)
        layout.addWidget(self._empty)
        layout.addWidget(scroll, 1)
        self.set_step(-1, None)

    def set_step(self, index: int, step: dict[str, Any] | None) -> None:
        self._step_index = index
        self._step = step
        self._step_type = str(step.get("type", "")) if step is not None else ""
        while self._form.rowCount():
            self._form.removeRow(0)
        self._empty.setVisible(step is None)
        self._form_host.setVisible(step is not None)
        if step is None:
            return

        ordered = ("id", "type", "name", "enabled", "on_failure")
        keys = [key for key in ordered if key in step]
        keys.extend(
            key
            for key in step
            if key not in ordered and self._field_is_visible(key, step)
        )
        for key in keys:
            self._add_field(key, step[key])

    @staticmethod
    def _field_is_visible(key: str, step: dict[str, Any]) -> bool:
        step_type = step.get("type")
        if step_type == "wait":
            delay_mode = step.get("delay_mode", "fixed")
            if key == "duration_ms":
                return delay_mode == "fixed"
            if key in {"min_duration_ms", "max_duration_ms"}:
                return delay_mode == "random"
        if step_type == "mouse_move":
            move_mode = step.get("move_mode", "absolute")
            if key in {"x", "y"}:
                return move_mode == "absolute"
            if key in {"delta_x", "delta_y"}:
                return move_mode == "relative"
        if step_type == "template_match":
            post_action = step.get("post_action", "none")
            if key == "post_button":
                return post_action in {"click", "double_click"}
            if key == "post_action_interval_ms":
                return post_action == "double_click"
            if key in {"post_key", "post_modifiers", "post_key_hold_ms"}:
                return post_action == "key_press"
        return True

    def _add_field(self, key: str, value: Any) -> None:
        label = FIELD_LABELS.get(key, key)
        help_text = FIELD_HELP.get(key, f"配置“{label}”参数。")
        if key == "type":
            widget = QLabel(str(value))
            widget.setObjectName("mutedLabel")
        elif key == "template":
            widget = self._template_path_widget(value)
        elif key in CHOICES:
            widget = QComboBox()
            choices = CHOICES[key]
            if key == "on_failure" and self._step_type == "template_match":
                choices = (
                    ("停止工作流", "stop"),
                    ("再次运行（直到成功）", "retry"),
                    ("继续下一步", "continue"),
                )
            for text, stored in choices:
                widget.addItem(text, stored)
            selected = widget.findData(value)
            widget.setCurrentIndex(max(0, selected))
            widget.currentIndexChanged.connect(
                lambda _value, control=widget, field=key: self._emit(
                    field, control.currentData()
                )
            )
        elif isinstance(value, bool):
            widget = QCheckBox()
            widget.setChecked(value)
            widget.toggled.connect(lambda checked, field=key: self._emit(field, checked))
        elif isinstance(value, int):
            widget = QSpinBox()
            if key in {"delta_x", "delta_y"}:
                widget.setRange(-1_000_000, 1_000_000)
            else:
                widget.setRange(0, 1_000_000)
            widget.setValue(value)
            widget.editingFinished.connect(
                lambda control=widget, field=key: self._emit(field, control.value())
            )
        elif isinstance(value, float):
            widget = QDoubleSpinBox()
            widget.setRange(0.0, 1.0)
            widget.setDecimals(3)
            widget.setSingleStep(0.05)
            widget.setValue(value)
            widget.editingFinished.connect(
                lambda control=widget, field=key: self._emit(field, control.value())
            )
        else:
            widget = QLineEdit(self._format_value(value))
            if key == "text":
                widget.setPlaceholderText("输入要发送的文本")
            widget.editingFinished.connect(
                lambda control=widget, field=key, original=value: self._emit(
                    field,
                    self._parse_text(control.text(), original),
                )
            )
        widget.setAccessibleName(label)
        widget.setToolTip(help_text)
        field_label = QLabel(f"{label}：")
        field_label.setToolTip(help_text)
        field_label.setAccessibleName(f"{label}说明")
        self._form.addRow(field_label, widget)

    def _template_path_widget(self, value: Any) -> QWidget:
        host = QWidget()
        layout = QHBoxLayout(host)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        editor = QLineEdit(self._format_value(value))
        editor.setObjectName("templatePathEdit")
        editor.editingFinished.connect(
            lambda control=editor, original=value: self._emit(
                "template",
                self._parse_text(control.text(), original),
            )
        )
        select_button = QPushButton("选择文件")
        select_button.setObjectName("selectTemplateButton")
        select_button.setToolTip("从磁盘选择一张已有的 PNG、JPG、BMP 或 WebP 模板图片。")
        select_button.clicked.connect(
            lambda: self.template_select_requested.emit(self._step_index)
        )
        create_button = QPushButton("创建模板")
        create_button.setObjectName("createTemplateButton")
        create_button.setToolTip("按照引导从完整截图中框选区域，并保存为本地模板。")
        create_button.clicked.connect(
            lambda: self.template_create_requested.emit(self._step_index)
        )

        layout.addWidget(editor, 1)
        layout.addWidget(select_button)
        layout.addWidget(create_button)
        host.setAccessibleName("模板路径")
        return host

    @staticmethod
    def _format_value(value: Any) -> str:
        if isinstance(value, list):
            return ", ".join(str(item) for item in value)
        if value is None:
            return ""
        return str(value)

    @staticmethod
    def _parse_text(text: str, original: Any) -> Any:
        if isinstance(original, list):
            return [item.strip() for item in text.split(",") if item.strip()]
        if original is None:
            return text.strip() or None
        return text

    def _emit(self, field: str, value: object) -> None:
        if self._step_index >= 0:
            self.property_changed.emit(self._step_index, field, value)
