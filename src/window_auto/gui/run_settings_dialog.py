"""Dialog for run target mode, target window, and input strategy."""

from __future__ import annotations

from PySide6.QtCore import QSignalBlocker
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QRadioButton,
    QVBoxLayout,
    QWidget,
)

from window_auto.application.input_profiles import (
    INPUT_PROFILES,
    MODE_DESCRIPTIONS,
    MODE_LABELS,
    MODE_SCREENCAP_LABELS,
    InputProfileName,
    RunMode,
    default_input_profile,
    mode_input_profiles,
)
from window_auto.gui.window_dialog import WindowSelectorDialog
from window_auto.windowing.discovery import WindowInfo


PROFILE_LABELS = {
    InputProfileName.BACKGROUND_MESSAGE: "后台消息（兼容性中）",
    InputProfileName.BACKGROUND_WINDOW_MESSAGE: "窗口后台消息（目标需支持）",
    InputProfileName.FOREGROUND_PRECISE: "前台精确点击（推荐）",
    InputProfileName.FOREGROUND_COMPATIBLE: "前台兼容（目标须在前台）",
    InputProfileName.DRIVER_INTERCEPTION: "驱动级（需管理员）",
}


class RunSettingsDialog(QDialog):
    """Edit the run target mode, the target window, and the input profile."""

    def __init__(
        self,
        mode: RunMode,
        selected_window: WindowInfo | None,
        profile_name: InputProfileName,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("运行设置")
        self.setMinimumWidth(480)
        self.result_mode = mode
        self.selected_window = selected_window
        self.result_profile = profile_name

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)

        self._mode_radios: dict[RunMode, QRadioButton] = {}
        for value in RunMode:
            radio = QRadioButton(MODE_LABELS[value])
            radio.setChecked(value == mode)
            description = QLabel(MODE_DESCRIPTIONS[value])
            description.setObjectName("mutedLabel")
            description.setWordWrap(True)
            description.setIndent(22)
            layout.addWidget(radio)
            layout.addWidget(description)
            self._mode_radios[value] = radio

        window_row = QHBoxLayout()
        window_row.addWidget(QLabel("目标窗口："))
        self.window_label = QLabel()
        self.window_label.setObjectName("mutedLabel")
        window_row.addWidget(self.window_label, 1)
        self.select_window_button = QPushButton("选择窗口…")
        self.select_window_button.setObjectName("selectRunWindowButton")
        window_row.addWidget(self.select_window_button)
        layout.addLayout(window_row)

        profile_row = QHBoxLayout()
        profile_row.addWidget(QLabel("输入策略："))
        self.profile_combo = QComboBox()
        profile_row.addWidget(self.profile_combo, 1)
        layout.addLayout(profile_row)

        screencap_row = QHBoxLayout()
        screencap_row.addWidget(QLabel("截图方式："))
        self.screencap_label = QLabel()
        self.screencap_label.setObjectName("mutedLabel")
        screencap_row.addWidget(self.screencap_label, 1)
        layout.addLayout(screencap_row)

        self.warning_label = QLabel()
        self.warning_label.setObjectName("mutedLabel")
        self.warning_label.setWordWrap(True)
        layout.addWidget(self.warning_label)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("确定")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("取消")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        for value, radio in self._mode_radios.items():
            radio.toggled.connect(
                lambda checked, changed=value: checked and self._apply_mode(changed)
            )
        self.select_window_button.clicked.connect(self._choose_window)
        self.profile_combo.currentIndexChanged.connect(self._on_profile_changed)

        self._apply_mode(mode, preferred_profile=profile_name)

    def _apply_mode(
        self,
        mode: RunMode,
        preferred_profile: InputProfileName | None = None,
    ) -> None:
        self.result_mode = mode
        fullscreen = mode is RunMode.FULLSCREEN
        self.select_window_button.setEnabled(not fullscreen)
        self._refresh_window_label()
        self.screencap_label.setText(MODE_SCREENCAP_LABELS[mode])

        available = mode_input_profiles(mode)
        profile = preferred_profile or self.profile_combo.currentData()
        if profile not in available:
            profile = default_input_profile(mode)
        with QSignalBlocker(self.profile_combo):
            self.profile_combo.clear()
            for name in available:
                self.profile_combo.addItem(PROFILE_LABELS[name], name)
            self.profile_combo.setCurrentIndex(self.profile_combo.findData(profile))
        self.result_profile = profile
        self._refresh_warning()

    def _refresh_window_label(self) -> None:
        if self.result_mode is RunMode.FULLSCREEN:
            self.window_label.setText("整个屏幕（无需选择窗口）")
        elif self.selected_window is None:
            self.window_label.setText("未选择（运行前必须选择）")
        else:
            window = self.selected_window
            self.window_label.setText(f"{window.title} · {window.class_name}")
            self.window_label.setToolTip(
                f"HWND 0x{window.hwnd:X} · 客户区 {window.client_width}×{window.client_height}"
            )

    def _on_profile_changed(self) -> None:
        profile = self.profile_combo.currentData()
        if profile is not None:
            self.result_profile = profile
        self._refresh_warning()

    def _refresh_warning(self) -> None:
        profile = INPUT_PROFILES.get(self.profile_combo.currentData())
        self.warning_label.setText(profile.warning if profile is not None else "")

    def _choose_window(self) -> None:
        dialog = WindowSelectorDialog(self)
        if dialog.exec() and dialog.selected_window is not None:
            self.selected_window = dialog.selected_window
            self._refresh_window_label()
