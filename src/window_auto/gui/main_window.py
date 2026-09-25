"""Main window for the Window Auto workflow editor."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QSize, Qt, QThread, QTimer
from PySide6.QtGui import QAction, QCloseEvent, QKeySequence
from PySide6.QtWidgets import (
    QComboBox,
    QDockWidget,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSizePolicy,
    QSplitter,
    QStatusBar,
    QToolBar,
    QVBoxLayout,
    QWidget,
)

from window_auto.application.input_profiles import INPUT_PROFILES, InputProfileName
from window_auto.config.loader import load_config
from window_auto.diagnostics.workspace import create_debug_workspace
from window_auto.gui.document import STEP_LABELS, WorkflowDocument
from window_auto.gui.property_editor import PropertyEditor
from window_auto.gui.template_creator import TemplateCreationDialog
from window_auto.gui.window_dialog import WindowSelectorDialog
from window_auto.gui.worker import WorkflowWorker
from window_auto.paths import project_root
from window_auto.windowing.discovery import WindowInfo
from window_auto.workflow.events import WorkflowEvent, WorkflowEventType
from window_auto.workflow.loader import WorkflowV2ConfigError, load_workflow_v2


PROJECT_ROOT = project_root()
DEFAULT_CONFIG_PATH = PROJECT_ROOT / "config" / "default.json"
STARTUP_LOG_PATH = PROJECT_ROOT / "debug" / "startup.log"
TEMPLATE_DIRECTORY = PROJECT_ROOT / "assets" / "resource" / "image"
EVENT_LABELS = {
    WorkflowEventType.WORKFLOW_STARTED: "工作流已开始",
    WorkflowEventType.STEP_STARTED: "步骤已开始",
    WorkflowEventType.STEP_SUCCEEDED: "步骤已完成",
    WorkflowEventType.STEP_FAILED: "步骤失败",
    WorkflowEventType.STEP_SKIPPED: "步骤已跳过",
    WorkflowEventType.WORKFLOW_CANCELLED: "工作流已停止",
    WorkflowEventType.WORKFLOW_FAILED: "工作流失败",
    WorkflowEventType.WORKFLOW_SUCCEEDED: "工作流已完成",
}


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.document = WorkflowDocument()
        self.selected_window: WindowInfo | None = None
        self._thread: QThread | None = None
        self._worker: WorkflowWorker | None = None
        self.setWindowTitle("LN-auto 工作流编辑器")
        self.resize(1360, 820)
        self.setMinimumSize(1024, 640)
        self._build_actions()
        self._build_menus()
        self._build_toolbar()
        self._build_central()
        self._build_log_dock()
        self._load_startup_log()
        self.setStatusBar(QStatusBar())
        self.statusBar().showMessage("就绪")
        self._refresh_document()

    def _build_actions(self) -> None:
        self.new_action = QAction("新建", self)
        self.new_action.setShortcut(QKeySequence.StandardKey.New)
        self.new_action.triggered.connect(self.new_document)
        self.open_action = QAction("打开", self)
        self.open_action.setShortcut(QKeySequence.StandardKey.Open)
        self.open_action.triggered.connect(self.open_document)
        self.save_action = QAction("保存", self)
        self.save_action.setShortcut(QKeySequence.StandardKey.Save)
        self.save_action.triggered.connect(self.save_document)
        self.save_as_action = QAction("另存为", self)
        self.save_as_action.setShortcut(QKeySequence.StandardKey.SaveAs)
        self.save_as_action.triggered.connect(lambda: self.save_document(save_as=True))

    def _build_menus(self) -> None:
        file_menu = self.menuBar().addMenu("文件(&F)")
        file_menu.addAction(self.new_action)
        file_menu.addAction(self.open_action)
        file_menu.addAction(self.save_action)
        file_menu.addAction(self.save_as_action)

    def _build_toolbar(self) -> None:
        toolbar = QToolBar("主工具栏")
        toolbar.setMovable(False)
        toolbar.addAction(self.new_action)
        toolbar.addAction(self.open_action)
        toolbar.addAction(self.save_action)
        toolbar.addSeparator()

        self.target_label = QLabel("未选择目标窗口")
        self.target_label.setObjectName("mutedLabel")
        self.target_label.setMinimumWidth(280)
        select_window = QPushButton("选择窗口")
        select_window.clicked.connect(self.choose_window)
        toolbar.addWidget(self.target_label)
        toolbar.addWidget(select_window)
        toolbar.addSeparator()

        toolbar.addWidget(QLabel("输入策略："))
        self.profile_combo = QComboBox()
        for name, profile in INPUT_PROFILES.items():
            label = {
                InputProfileName.BACKGROUND_MESSAGE: "后台消息（兼容性中）",
                InputProfileName.BACKGROUND_WINDOW_MESSAGE: "窗口后台消息（目标需支持）",
                InputProfileName.FOREGROUND_PRECISE: "前台精确点击（推荐）",
                InputProfileName.FOREGROUND_COMPATIBLE: "前台兼容（需窗口置顶）",
                InputProfileName.DRIVER_INTERCEPTION: "驱动级（需管理员）",
            }[name]
            self.profile_combo.addItem(label, profile)
        self.profile_combo.setCurrentIndex(
            self.profile_combo.findData(
                INPUT_PROFILES[InputProfileName.FOREGROUND_PRECISE]
            )
        )
        toolbar.addWidget(self.profile_combo)

        spacer = QWidget()
        spacer.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Preferred,
        )
        toolbar.addWidget(spacer)
        self.stop_button = QPushButton("停止")
        self.stop_button.setObjectName("dangerButton")
        self.stop_button.setEnabled(False)
        self.stop_button.clicked.connect(self.stop_workflow)
        self.run_button = QPushButton("运行工作流")
        self.run_button.setObjectName("primaryButton")
        self.run_button.clicked.connect(self.run_workflow)
        toolbar.addWidget(self.stop_button)
        toolbar.addWidget(self.run_button)
        self.addToolBar(toolbar)

    def _build_central(self) -> None:
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(self._build_palette())
        splitter.addWidget(self._build_steps())
        self.properties = PropertyEditor()
        self.properties.property_changed.connect(self.update_property)
        self.properties.template_select_requested.connect(self.select_template_file)
        self.properties.template_create_requested.connect(self.create_template)
        splitter.addWidget(self.properties)
        splitter.setSizes((230, 420, 610))
        splitter.setCollapsible(0, False)
        splitter.setCollapsible(1, False)
        splitter.setCollapsible(2, False)
        self.setCentralWidget(splitter)

    def _build_palette(self) -> QWidget:
        host = QWidget()
        layout = QVBoxLayout(host)
        layout.setContentsMargins(12, 12, 8, 12)
        title = QLabel("动作组件")
        title.setObjectName("sectionTitle")
        help_text = QLabel("双击动作，或选择后点击“添加”。")
        help_text.setObjectName("mutedLabel")
        self.palette = QListWidget()
        for step_type, label in STEP_LABELS.items():
            item = QListWidgetItem(label)
            item.setData(Qt.ItemDataRole.UserRole, step_type)
            self.palette.addItem(item)
        self.palette.itemDoubleClicked.connect(lambda _item: self.add_selected_action())
        add_button = QPushButton("添加到工作流")
        add_button.clicked.connect(self.add_selected_action)
        layout.addWidget(title)
        layout.addWidget(help_text)
        layout.addWidget(self.palette, 1)
        layout.addWidget(add_button)
        return host

    def _build_steps(self) -> QWidget:
        host = QWidget()
        layout = QVBoxLayout(host)
        layout.setContentsMargins(8, 12, 8, 12)
        title_row = QHBoxLayout()
        title = QLabel("工作流步骤")
        title.setObjectName("sectionTitle")
        self.workflow_name = QLabel()
        self.workflow_name.setObjectName("mutedLabel")
        title_row.addWidget(title)
        title_row.addStretch()
        title_row.addWidget(self.workflow_name)
        self.step_list = QListWidget()
        self.step_list.setAlternatingRowColors(True)
        self.step_list.currentRowChanged.connect(self.select_step)
        controls = QHBoxLayout()
        for text, callback in (
            ("上移", lambda: self.move_step(-1)),
            ("下移", lambda: self.move_step(1)),
            ("删除", self.remove_step),
        ):
            button = QPushButton(text)
            button.clicked.connect(callback)
            controls.addWidget(button)
        controls.addStretch()
        layout.addLayout(title_row)
        layout.addWidget(self.step_list, 1)
        layout.addLayout(controls)
        return host

    def _build_log_dock(self) -> None:
        dock = QDockWidget("运行日志", self)
        dock.setAllowedAreas(
            Qt.DockWidgetArea.BottomDockWidgetArea | Qt.DockWidgetArea.RightDockWidgetArea
        )
        self.log_view = QPlainTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setMaximumBlockCount(2000)
        self.log_view.setAccessibleName("工作流运行日志")
        dock.setWidget(self.log_view)
        self.addDockWidget(Qt.DockWidgetArea.BottomDockWidgetArea, dock)

    def _load_startup_log(self) -> None:
        if not STARTUP_LOG_PATH.is_file():
            return
        try:
            lines = STARTUP_LOG_PATH.read_text(
                encoding="utf-8",
                errors="replace",
            ).splitlines()
        except OSError as error:
            self.append_log(f"无法读取启动日志：{error}")
            return
        for line in lines:
            if line.strip():
                self.append_log(f"启动 · {line}")

    def _refresh_document(self, selected_row: int | None = None) -> None:
        self.workflow_name.setText(self.document.name)
        self.step_list.clear()
        for index, step in enumerate(self.document.steps, start=1):
            enabled = "" if step.get("enabled", True) else "（已禁用）"
            label = STEP_LABELS.get(step.get("type"), str(step.get("type")))
            item = QListWidgetItem(
                f"{index:02d}  {step.get('name', label)}\n      {label}  ·  {step.get('id')} {enabled}"
            )
            item.setToolTip(str(step))
            self.step_list.addItem(item)
        if not self.document.steps:
            empty = QListWidgetItem(
                "还没有步骤\n\n从左侧选择动作并添加，工作流将按从上到下的顺序执行。"
            )
            empty.setFlags(Qt.ItemFlag.NoItemFlags)
            empty.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.step_list.addItem(empty)
        self._update_title()
        if selected_row is not None and self.document.steps:
            self.step_list.setCurrentRow(
                min(max(selected_row, 0), self.step_list.count() - 1)
            )
        elif not self.document.steps:
            self.properties.set_step(-1, None)

    def _update_title(self) -> None:
        marker = " *" if self.document.dirty else ""
        path = self.document.path.name if self.document.path else "未命名"
        self.setWindowTitle(f"{path}{marker} — LN-auto 工作流编辑器")

    def add_selected_action(self) -> None:
        item = self.palette.currentItem() or self.palette.item(0)
        index = self.document.add_step(item.data(Qt.ItemDataRole.UserRole))
        self._refresh_document(index)

    def select_step(self, row: int) -> None:
        step = self.document.steps[row] if 0 <= row < len(self.document.steps) else None
        self.properties.set_step(row, step)

    def update_property(self, index: int, field: str, value: object) -> None:
        try:
            self.document.update_step(index, field, value)
        except ValueError as error:
            QMessageBox.warning(self, "无法更新属性", str(error))
        # Property changes originate from controls inside PropertyEditor. Rebuilding
        # the form synchronously here would delete the signal sender while Qt is
        # still dispatching its signal, which can cause a native use-after-free.
        QTimer.singleShot(0, lambda row=index: self._refresh_document(row))

    def _set_template_path(self, index: int, path: Path) -> None:
        if not 0 <= index < len(self.document.steps):
            return
        if self.document.steps[index].get("type") != "template_match":
            return
        resolved = path.resolve()
        try:
            stored_path = resolved.relative_to(PROJECT_ROOT).as_posix()
        except ValueError:
            stored_path = resolved.as_posix()
        self.document.update_step(index, "template", stored_path)
        self._refresh_document(index)
        self._update_title()

    def select_template_file(self, index: int) -> None:
        filename, _ = QFileDialog.getOpenFileName(
            self,
            "选择模板图片",
            str(TEMPLATE_DIRECTORY),
            "图片文件 (*.png *.jpg *.jpeg *.bmp *.webp)",
        )
        if not filename:
            return
        self._set_template_path(index, Path(filename))
        self.statusBar().showMessage(f"已选择模板：{filename}", 5000)
        self.append_log(f"模板文件已选择：{filename}")

    def create_template(self, index: int) -> None:
        if not 0 <= index < len(self.document.steps):
            return
        guide = (
            "创建模板需要一张包含目标界面的完整截图。\n\n"
            "1. 先让目标界面停留在需要识别的画面，并截取原始画面。\n"
            "2. 在下一步选择这张截图，不要提前缩放图片；保存时会自动换算到识别分辨率。\n"
            "3. 在截图中拖动框选稳定、清晰且唯一的图形区域。\n"
            "4. 输入名称后保存；模板会存入项目的本地模板目录。\n\n"
            "避免框选动画、倒计时、动态文本和会变化的数字。"
        )
        QMessageBox.information(self, "模板创建引导", guide)

        screenshot_directory = PROJECT_ROOT / "debug" / "screenshots"
        if not screenshot_directory.is_dir():
            screenshot_directory = PROJECT_ROOT
        filename, _ = QFileDialog.getOpenFileName(
            self,
            "选择用于创建模板的完整截图",
            str(screenshot_directory),
            "截图图片 (*.png *.jpg *.jpeg *.bmp *.webp)",
        )
        if not filename:
            return
        try:
            recognition_size = None
            try:
                config = load_config(DEFAULT_CONFIG_PATH)
                expected = config["controller"]["expected_screenshot_resolution"]
                recognition_size = QSize(int(expected[0]), int(expected[1]))
            except (OSError, ValueError, KeyError, IndexError, TypeError):
                recognition_size = None
            dialog = TemplateCreationDialog(
                Path(filename),
                TEMPLATE_DIRECTORY,
                self,
                recognition_size=recognition_size,
            )
        except (OSError, ValueError) as error:
            QMessageBox.critical(self, "无法创建模板", str(error))
            return
        if not dialog.exec() or dialog.saved_path is None:
            return
        self._set_template_path(index, dialog.saved_path)
        relative_path = dialog.saved_path.relative_to(PROJECT_ROOT).as_posix()
        if dialog.normalized_for_recognition and dialog.recognition_size is not None:
            self.append_log(
                "模板已按识别分辨率 "
                f"{dialog.recognition_size.width()}×{dialog.recognition_size.height()} 缩放。"
            )
        self.statusBar().showMessage(f"模板已创建：{relative_path}", 6000)
        self.append_log(f"模板已创建并设置到当前步骤：{relative_path}")

    def move_step(self, offset: int) -> None:
        row = self.step_list.currentRow()
        if 0 <= row < len(self.document.steps):
            self._refresh_document(self.document.move_step(row, offset))

    def remove_step(self) -> None:
        row = self.step_list.currentRow()
        if not 0 <= row < len(self.document.steps):
            return
        step = self.document.steps[row]
        answer = QMessageBox.question(
            self,
            "删除步骤",
            f"确定删除“{step.get('name')}”吗？",
        )
        if answer == QMessageBox.StandardButton.Yes:
            self.document.remove_step(row)
            self._refresh_document(max(0, row - 1))

    def new_document(self) -> None:
        if not self._confirm_discard():
            return
        self.document = WorkflowDocument()
        self.selected_window = None
        self.target_label.setText("未选择目标窗口")
        self.target_label.setToolTip("")
        self._refresh_document()

    def open_document(self) -> None:
        if not self._confirm_discard():
            return
        filename, _ = QFileDialog.getOpenFileName(
            self,
            "打开工作流",
            str(PROJECT_ROOT / "config"),
            "工作流 JSON (*.json)",
        )
        if not filename:
            return
        try:
            self.document = WorkflowDocument.load(Path(filename), PROJECT_ROOT)
        except Exception as error:
            QMessageBox.critical(self, "无法打开工作流", str(error))
            return
        self.selected_window = None
        self.target_label.setText("未选择目标窗口")
        self.target_label.setToolTip("")
        self._refresh_document(0)
        self.statusBar().showMessage(f"已打开 {filename}", 4000)

    def save_document(self, save_as: bool = False) -> bool:
        path = self.document.path
        if save_as or path is None:
            filename, _ = QFileDialog.getSaveFileName(
                self,
                "保存工作流",
                str(PROJECT_ROOT / "config" / "workflow.local.json"),
                "工作流 JSON (*.json)",
            )
            if not filename:
                return False
            path = Path(filename)
        try:
            saved = self.document.save(path, PROJECT_ROOT)
        except WorkflowV2ConfigError as error:
            QMessageBox.critical(
                self,
                "无法保存工作流",
                f"当前配置未通过校验，文件未保存。请修正后重试：\n{error}",
            )
            return False
        except Exception as error:
            QMessageBox.critical(self, "保存失败", str(error))
            return False
        self._update_title()
        self.statusBar().showMessage(f"已保存 {saved}", 4000)
        return True

    def choose_window(self) -> None:
        dialog = WindowSelectorDialog(self)
        if dialog.exec() and dialog.selected_window is not None:
            self.selected_window = dialog.selected_window
            window = dialog.selected_window
            self.target_label.setText(f"{window.title}  ·  {window.class_name}")
            self.target_label.setToolTip(
                f"HWND 0x{window.hwnd:X} · 客户区 {window.client_width}×{window.client_height}"
            )
            self.document.set_target(window.title, window.class_name)
            self._update_title()

    def run_workflow(self) -> None:
        if self._thread is not None:
            return
        if self.selected_window is None:
            QMessageBox.information(self, "尚未选择窗口", "请先选择唯一的目标窗口。")
            return
        if self.document.dirty or self.document.path is None:
            if not self.save_document():
                return
        try:
            definition = load_workflow_v2(self.document.path, PROJECT_ROOT)
            config = load_config(DEFAULT_CONFIG_PATH)
        except (WorkflowV2ConfigError, OSError, ValueError) as error:
            QMessageBox.critical(self, "工作流无法运行", str(error))
            return

        profile = self.profile_combo.currentData()
        warning = (
            f"目标：{self.selected_window.title}\n"
            f"输入策略：{self.profile_combo.currentText()}\n\n"
            f"{profile.warning}\n\n"
            "运行期间可能发送鼠标和键盘输入。是否继续？"
        )
        if (
            QMessageBox.warning(
                self,
                "确认运行工作流",
                warning,
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
                QMessageBox.StandardButton.Cancel,
            )
            != QMessageBox.StandardButton.Yes
        ):
            return

        workspace = create_debug_workspace(
            PROJECT_ROOT,
            config["diagnostics"]["debug_dir"],
        )
        self._thread = QThread(self)
        self._worker = WorkflowWorker(
            definition,
            self.selected_window,
            config,
            PROJECT_ROOT,
            workspace,
            profile,
        )
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.event_received.connect(self.on_workflow_event)
        self._worker.finished.connect(self.on_workflow_finished)
        self._worker.finished.connect(self._thread.quit)
        self._worker.finished.connect(self._worker.deleteLater)
        self._thread.finished.connect(self._thread.deleteLater)
        self._thread.finished.connect(self._clear_worker)
        self.run_button.setEnabled(False)
        self.stop_button.setEnabled(True)
        self.statusBar().showMessage("工作流运行中…")
        self.append_log(f"开始运行：{definition.name}")
        self._thread.start()

    def stop_workflow(self) -> None:
        if self._worker is not None:
            self._worker.cancel()
            self.stop_button.setEnabled(False)
            self.statusBar().showMessage("正在安全停止…")
            self.append_log("已请求停止，将在当前安全边界结束。")

    def on_workflow_event(self, event: object) -> None:
        if isinstance(event, WorkflowEvent):
            text = EVENT_LABELS.get(event.type, event.type.value)
            if event.step_name:
                text += f" · {event.step_name}"
            if event.message:
                text += f" · {event.message}"
        elif isinstance(event, dict) and event.get("type") == "cleanup_failed":
            text = f"控制器清理失败 · {event.get('message', '')}".rstrip(" ·")
        else:
            text = str(event)
        self.append_log(text)

    def on_workflow_finished(self, succeeded: bool, message: str) -> None:
        self.append_log(message)
        self.statusBar().showMessage(message, 8000)
        was_cancelled = self._worker is not None and self._worker.cancellation.cancelled
        if not succeeded and not was_cancelled:
            QMessageBox.critical(
                self,
                "工作流运行失败",
                f"{message}\n\n请检查目标窗口、分辨率和输入策略，然后查看运行日志后重试。",
            )

    def _clear_worker(self) -> None:
        self._worker = None
        self._thread = None
        self.run_button.setEnabled(True)
        self.stop_button.setEnabled(False)

    def append_log(self, message: str) -> None:
        timestamp = datetime.now().strftime("%H:%M:%S")
        self.log_view.appendPlainText(f"[{timestamp}] {message}")

    def _confirm_discard(self) -> bool:
        if not self.document.dirty:
            return True
        answer = QMessageBox.question(
            self,
            "未保存的更改",
            "当前工作流有未保存更改。是否保存？",
            QMessageBox.StandardButton.Save
            | QMessageBox.StandardButton.Discard
            | QMessageBox.StandardButton.Cancel,
        )
        if answer == QMessageBox.StandardButton.Save:
            return self.save_document()
        return answer == QMessageBox.StandardButton.Discard

    def closeEvent(self, event: QCloseEvent) -> None:
        if self._thread is not None:
            QMessageBox.information(
                self,
                "工作流仍在运行",
                "请先停止工作流，等待控制器安全释放后再关闭。",
            )
            event.ignore()
            return
        if self._confirm_discard():
            event.accept()
        else:
            event.ignore()
