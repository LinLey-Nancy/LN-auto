"""Rich item delegate and summary helpers for the workflow step list."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from PySide6.QtCore import QRectF, QSize, Qt
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPainterPath
from PySide6.QtWidgets import QStyle, QStyledItemDelegate, QStyleOptionViewItem

from window_auto.gui.document import STEP_LABELS


TYPE_COLORS = {
    "template_match": "#7C3AED",
    "mouse_move": "#0EA5E9",
    "mouse_click": "#2563EB",
    "key_press": "#16A34A",
    "text_input": "#EA580C",
    "wait": "#64748B",
    "run_workflow": "#DB2777",
}
TYPE_TAGS = {
    "template_match": "模板",
    "mouse_move": "移动",
    "mouse_click": "点击",
    "key_press": "按键",
    "text_input": "文本",
    "wait": "延迟",
    "run_workflow": "流程",
}
_BUTTON_LABELS = {"left": "左键", "right": "右键", "middle": "中键"}
_POST_ACTION_LABELS = {
    "click": "单击",
    "double_click": "双击",
    "key_press": "按键",
}


def _button_label(value: Any) -> str:
    return _BUTTON_LABELS.get(str(value), str(value))


def summarize_step(step: dict[str, Any]) -> str:
    """One-line description of a step's key parameters."""
    step_type = step.get("type")
    if step_type == "wait":
        if step.get("delay_mode") == "random":
            return f"随机 {step.get('min_duration_ms', 0)}~{step.get('max_duration_ms', 0)} 毫秒"
        return f"固定 {step.get('duration_ms', 0)} 毫秒"
    if step_type == "mouse_move":
        if step.get("move_mode") == "relative":
            return f"相对移动 ({step.get('delta_x', 0):+}, {step.get('delta_y', 0):+})"
        return f"移动到 ({step.get('x', 0)}, {step.get('y', 0)})"
    if step_type == "mouse_click":
        button = _button_label(step.get("button", "left"))
        if step.get("match_variable"):
            target = f"识别结果「{step['match_variable']}」"
        else:
            target = f"({step.get('x', 0)}, {step.get('y', 0)})"
        count = int(step.get("count", 1) or 1)
        verb = "双击" if count == 2 else "点击"
        return f"{button}{verb} {target}"
    if step_type == "key_press":
        modifiers = step.get("modifiers") or []
        prefix = "+".join(str(item) for item in modifiers)
        key = f"{prefix}+{step.get('key', '')}" if prefix else str(step.get("key", ""))
        return f"按键 {key}"
    if step_type == "text_input":
        text = str(step.get("text", ""))
        if step.get("sensitive"):
            return f"输入敏感内容（{len(text)} 字）"
        shown = text if len(text) <= 16 else text[:16] + "…"
        return f"输入“{shown}”"
    if step_type == "template_match":
        name = Path(str(step.get("template", ""))).name or "未设置"
        summary = f"模板 {name} · 阈值 {step.get('threshold', 0.8)}"
        post = _POST_ACTION_LABELS.get(str(step.get("post_action", "none")))
        if post:
            summary += f" · 识别后{post}"
        return summary
    if step_type == "run_workflow":
        workflow = str(step.get("workflow", "")).strip()
        return f"子工作流 {workflow or '（未设置）'}"
    return ""


class StepItemDelegate(QStyledItemDelegate):
    """Paint a step row with a colored type chip and a parameter summary."""

    ROW_HEIGHT = 56

    def sizeHint(self, option: QStyleOptionViewItem, index) -> QSize:
        if not isinstance(index.data(Qt.ItemDataRole.UserRole), dict):
            return super().sizeHint(option, index)
        return QSize(option.rect.width(), self.ROW_HEIGHT)

    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index) -> None:
        step = index.data(Qt.ItemDataRole.UserRole)
        if not isinstance(step, dict):
            super().paint(painter, option, index)
            return
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        rect = option.rect
        selected = bool(option.state & QStyle.StateFlag.State_Selected)
        alternate = bool(option.features & QStyleOptionViewItem.ViewItemFeature.Alternate)
        enabled = bool(step.get("enabled", True))

        if selected:
            painter.fillRect(rect, QColor("#312E81"))
        elif alternate:
            painter.fillRect(rect, QColor("#172033"))

        step_type = str(step.get("type", ""))
        label = STEP_LABELS.get(step_type, step_type)

        margin = 10
        chip_rect = QRectF(
            rect.left() + margin, rect.top() + (rect.height() - 26) / 2, 44, 26
        )
        chip_path = QPainterPath()
        chip_path.addRoundedRect(chip_rect, 6, 6)
        chip_color = TYPE_COLORS.get(step_type, "#475569")
        painter.fillPath(chip_path, QColor(chip_color) if enabled else QColor("#3B475C"))

        tag_font = QFont(option.font)
        tag_font.setBold(True)
        painter.setFont(tag_font)
        painter.setPen(QColor("#FFFFFF") if enabled else QColor("#94A3B8"))
        painter.drawText(
            chip_rect, Qt.AlignmentFlag.AlignCenter, TYPE_TAGS.get(step_type, "步骤")
        )

        text_left = chip_rect.right() + 10
        text_width = rect.right() - text_left - margin

        title_font = QFont(option.font)
        title_font.setBold(True)
        painter.setFont(title_font)
        painter.setPen(QColor("#FFFFFF") if selected else QColor("#F8FAFC"))
        if not enabled:
            painter.setPen(QColor("#7A879B"))
        title = f"{index.row() + 1:02d}  {step.get('name', label)}"
        title_rect = QRectF(text_left, rect.top() + 7, text_width, 22)
        painter.drawText(
            title_rect,
            Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
            QFontMetrics(title_font).elidedText(
                title, Qt.TextElideMode.ElideRight, int(text_width)
            ),
        )

        sub_font = QFont(option.font)
        sub_font.setPointSizeF(max(7.0, option.font.pointSizeF() - 1.5))
        painter.setFont(sub_font)
        painter.setPen(QColor("#CBD5E1") if selected else QColor("#94A3B8"))
        if not enabled:
            painter.setPen(QColor("#64748B"))
        parts = [label, str(step.get("id", ""))]
        summary = summarize_step(step)
        if summary:
            parts.append(summary)
        sub = " · ".join(parts)
        if not enabled:
            sub = f"已禁用 · {sub}"
        sub_rect = QRectF(text_left, rect.top() + 30, text_width, 20)
        painter.drawText(
            sub_rect,
            Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
            QFontMetrics(sub_font).elidedText(
                sub, Qt.TextElideMode.ElideRight, int(text_width)
            ),
        )
        painter.restore()
