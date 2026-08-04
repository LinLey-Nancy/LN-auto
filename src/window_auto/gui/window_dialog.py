"""Read-only target window picker."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from window_auto.application.window_service import WindowQuery, list_windows
from window_auto.windowing.discovery import WindowInfo


class WindowSelectorDialog(QDialog):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("选择目标窗口")
        self.resize(900, 520)
        self.selected_window: WindowInfo | None = None
        self._windows: list[WindowInfo] = []

        self.filter_edit = QLineEdit()
        self.filter_edit.setPlaceholderText("按窗口标题筛选")
        self.filter_edit.setAccessibleName("窗口标题筛选")
        self.visible_only = QCheckBox("仅显示可见窗口")
        self.visible_only.setChecked(True)
        refresh = QPushButton("刷新")
        refresh.clicked.connect(self.refresh)

        controls = QHBoxLayout()
        controls.addWidget(QLabel("标题："))
        controls.addWidget(self.filter_edit, 1)
        controls.addWidget(self.visible_only)
        controls.addWidget(refresh)

        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(
            ("标题", "窗口类", "客户区", "可见", "最小化", "HWND")
        )
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setStretchLastSection(False)
        self.table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.Stretch
        )
        self.table.doubleClicked.connect(self.accept)

        note = QLabel(
            "此列表为只读枚举。选择窗口不会创建控制器、截图或发送任何输入。"
        )
        note.setObjectName("mutedLabel")
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("选择")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("取消")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)
        layout.addLayout(controls)
        layout.addWidget(self.table, 1)
        layout.addWidget(note)
        layout.addWidget(buttons)
        self.refresh()

    def refresh(self) -> None:
        self._windows = list_windows(
            WindowQuery(
                title=self.filter_edit.text().strip() or None,
                visible_only=self.visible_only.isChecked(),
            )
        )
        self.table.setRowCount(len(self._windows))
        for row, window in enumerate(self._windows):
            values = (
                window.title,
                window.class_name,
                f"{window.client_width}×{window.client_height}",
                "是" if window.visible else "否",
                "是" if window.minimized else "否",
                f"0x{window.hwnd:X}",
            )
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                if column in (2, 3, 4, 5):
                    item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                self.table.setItem(row, column, item)
        if self._windows:
            self.table.selectRow(0)

    def accept(self) -> None:
        row = self.table.currentRow()
        if 0 <= row < len(self._windows):
            self.selected_window = self._windows[row]
            super().accept()
