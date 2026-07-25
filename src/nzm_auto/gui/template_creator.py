"""Guided image cropping dialog for creating local recognition templates."""

from __future__ import annotations

from pathlib import Path
import re

from PySide6.QtCore import QPoint, QRect, QSize, Qt
from PySide6.QtGui import QColor, QMouseEvent, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)


def safe_template_stem(value: str) -> str:
    """Return a filesystem-safe template name without an extension."""
    stem = re.sub(r"[^\w.-]+", "_", value.strip(), flags=re.UNICODE).strip("._")
    return stem or "template"


def unique_template_path(directory: Path, requested_name: str) -> Path:
    """Choose a PNG path without overwriting an existing local template."""
    directory.mkdir(parents=True, exist_ok=True)
    stem = safe_template_stem(Path(requested_name).stem)
    candidate = directory / f"{stem}.png"
    sequence = 2
    while candidate.exists():
        candidate = directory / f"{stem}-{sequence}.png"
        sequence += 1
    return candidate


def map_selection_to_source(
    selection: QRect,
    display_size: QSize,
    source_size: QSize,
) -> QRect:
    """Map the visible crop rectangle back to original image pixels."""
    if (
        selection.width() <= 0
        or selection.height() <= 0
        or display_size.width() <= 0
        or display_size.height() <= 0
    ):
        return QRect()
    scale_x = source_size.width() / display_size.width()
    scale_y = source_size.height() / display_size.height()
    left = max(0, round(selection.left() * scale_x))
    top = max(0, round(selection.top() * scale_y))
    right = min(
        source_size.width(),
        round((selection.right() + 1) * scale_x),
    )
    bottom = min(
        source_size.height(),
        round((selection.bottom() + 1) * scale_y),
    )
    return QRect(left, top, max(0, right - left), max(0, bottom - top))


def scale_crop_to_recognition(
    cropped: QPixmap,
    source_size: QSize,
    recognition_size: QSize | None,
) -> QPixmap:
    """Scale a raw screenshot crop to the Maa recognition image size."""
    if recognition_size is None or cropped.isNull():
        return cropped
    if (
        source_size.width() <= 0
        or source_size.height() <= 0
        or recognition_size.width() <= 0
        or recognition_size.height() <= 0
        or source_size == recognition_size
    ):
        return cropped
    width = max(1, round(cropped.width() * recognition_size.width() / source_size.width()))
    height = max(1, round(cropped.height() * recognition_size.height() / source_size.height()))
    if width == cropped.width() and height == cropped.height():
        return cropped
    return cropped.scaled(
        width,
        height,
        Qt.AspectRatioMode.IgnoreAspectRatio,
        Qt.TransformationMode.SmoothTransformation,
    )


class TemplateSelectionLabel(QLabel):
    """Image label that lets the user drag one crop rectangle."""

    def __init__(self, pixmap: QPixmap, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._origin: QPoint | None = None
        self._selection = QRect()
        self.setPixmap(pixmap)
        self.setFixedSize(pixmap.size())
        self.setCursor(Qt.CursorShape.CrossCursor)
        self.setAccessibleName("模板截图框选区域")

    @property
    def selection(self) -> QRect:
        return QRect(self._selection)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._origin = event.position().toPoint()
            self._selection = QRect(self._origin, self._origin)
            self.update()
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self._origin is not None:
            self._selection = QRect(
                self._origin,
                event.position().toPoint(),
            ).normalized().intersected(self.rect())
            self.update()
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton and self._origin is not None:
            self._selection = QRect(
                self._origin,
                event.position().toPoint(),
            ).normalized().intersected(self.rect())
            self._origin = None
            self.update()
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        if self._selection.isEmpty():
            return
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(0, 0, 0, 90))
        source_pixmap = self.pixmap()
        if source_pixmap is not None:
            painter.drawPixmap(
                self._selection,
                source_pixmap,
                self._selection,
            )
        painter.setPen(QPen(QColor("#A78BFA"), 3))
        painter.drawRect(self._selection.adjusted(1, 1, -1, -1))


class TemplateCreationDialog(QDialog):
    """Crop a screenshot and save it in the project's ignored template folder."""

    def __init__(
        self,
        source_path: Path,
        template_directory: Path,
        parent: QWidget | None = None,
        recognition_size: QSize | None = None,
    ) -> None:
        super().__init__(parent)
        self.source_path = source_path.resolve()
        self.template_directory = template_directory.resolve()
        self.recognition_size = recognition_size
        self.normalized_for_recognition = False
        self.saved_path: Path | None = None
        self._source_pixmap = QPixmap(str(self.source_path))
        if self._source_pixmap.isNull():
            raise ValueError(f"无法读取截图：{self.source_path}")

        self.setWindowTitle("创建识别模板")
        self.resize(1100, 780)

        instruction_text = (
            "在截图中按住鼠标左键拖动，框选需要识别的区域。\n"
            "建议只保留稳定、清晰且具有唯一性的图形；避开动画、计时、角色名称和会变化的数字。"
        )
        if (
            self.recognition_size is not None
            and self._source_pixmap.size() != self.recognition_size
        ):
            instruction_text += (
                f"\n保存时会自动换算到识别分辨率 "
                f"{self.recognition_size.width()}×{self.recognition_size.height()}。"
            )
        instructions = QLabel(instruction_text)
        instructions.setWordWrap(True)
        instructions.setObjectName("mutedLabel")

        display_pixmap = self._source_pixmap
        maximum_size = QSize(1000, 620)
        if (
            display_pixmap.width() > maximum_size.width()
            or display_pixmap.height() > maximum_size.height()
        ):
            display_pixmap = display_pixmap.scaled(
                maximum_size,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        self.selector = TemplateSelectionLabel(display_pixmap)

        scroll = QScrollArea()
        scroll.setWidget(self.selector)
        scroll.setWidgetResizable(False)
        scroll.setAlignment(Qt.AlignmentFlag.AlignCenter)

        name_label = QLabel("模板名称：")
        name_label.setToolTip("模板将以 PNG 格式保存在项目的本地模板目录中；同名文件不会被覆盖。")
        self.name_edit = QLineEdit(f"{self.source_path.stem}_template")
        self.name_edit.setAccessibleName("模板名称")
        self.name_edit.setToolTip(name_label.toolTip())

        name_row = QWidget()
        name_layout = QHBoxLayout(name_row)
        name_layout.setContentsMargins(0, 0, 0, 0)
        name_layout.addWidget(name_label)
        name_layout.addWidget(self.name_edit, 1)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save
            | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Save).setText("保存模板")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("取消")
        buttons.accepted.connect(self._save_template)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addWidget(instructions)
        layout.addWidget(scroll, 1)
        layout.addWidget(name_row)
        layout.addWidget(buttons)

    def _save_template(self) -> None:
        source_rect = map_selection_to_source(
            self.selector.selection,
            self.selector.size(),
            self._source_pixmap.size(),
        )
        if source_rect.width() < 2 or source_rect.height() < 2:
            QMessageBox.information(
                self,
                "尚未框选模板",
                "请在截图中按住鼠标左键，拖动框选一个至少 2×2 像素的区域。",
            )
            return
        output_path = unique_template_path(
            self.template_directory,
            self.name_edit.text(),
        )
        cropped = self._source_pixmap.copy(source_rect)
        scaled = scale_crop_to_recognition(
            cropped,
            self._source_pixmap.size(),
            self.recognition_size,
        )
        self.normalized_for_recognition = scaled.size() != cropped.size()
        if scaled.isNull() or not scaled.save(str(output_path), "PNG"):
            QMessageBox.critical(self, "保存失败", f"无法保存模板：{output_path}")
            return
        self.saved_path = output_path.resolve()
        self.accept()
