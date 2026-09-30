import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPoint, QSettings
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QDialog,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
)

from window_auto.application.input_profiles import InputProfileName, RunMode
from window_auto.gui.app import create_application
from window_auto.gui.document import WorkflowDocument
from window_auto.gui.main_window import MainWindow
from window_auto.gui.property_editor import PropertyEditor
from window_auto.gui.run_settings_dialog import RunSettingsDialog
from window_auto.runtime.win32_input import DirectInputError


class GuiSmokeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or create_application([])

    def test_standard_dialog_buttons_are_chinese(self) -> None:
        dialog = QMessageBox()
        dialog.setStandardButtons(
            QMessageBox.StandardButton.Save
            | QMessageBox.StandardButton.Discard
            | QMessageBox.StandardButton.Cancel
        )

        texts = {
            dialog.button(button).text().replace("&", "")
            for button in (
                QMessageBox.StandardButton.Save,
                QMessageBox.StandardButton.Discard,
                QMessageBox.StandardButton.Cancel,
            )
        }

        self.assertIn("保存", texts)
        self.assertIn("丢弃", texts)
        self.assertIn("取消", texts)

    def test_main_window_builds_and_adds_a_step(self) -> None:
        window = MainWindow()

        self.assertEqual(window.palette.count(), 8)
        self.assertFalse(window.stop_button.isEnabled())
        self.assertTrue(window.run_button.isEnabled())
        window.palette.setCurrentRow(5)
        window.add_selected_action()

        self.assertEqual(window.step_list.count(), 1)
        self.assertEqual(window.document.steps[0]["type"], "wait")
        window.document.dirty = False
        window.close()

    def test_add_button_inserts_below_selected_step(self) -> None:
        window = MainWindow()

        add_button = window.findChild(QPushButton, "insertStepButton")
        self.assertIsNotNone(add_button)
        self.assertEqual(add_button.text(), "插入到工作流")

        window.palette.setCurrentRow(5)
        window.add_selected_action()
        window.add_selected_action()
        window.step_list.setCurrentRow(0)
        window.palette.setCurrentRow(2)
        window.add_selected_action()

        self.assertEqual(
            [step["type"] for step in window.document.steps],
            ["wait", "mouse_click", "wait"],
        )
        window.document.dirty = False
        window.close()

    def test_mouse_position_is_shown_in_status_bar_corner(self) -> None:
        window = MainWindow()

        self.assertTrue(window._mouse_timer.isActive())
        window._update_mouse_position()
        self.assertRegex(
            window.mouse_position_label.text(),
            r"屏幕 X: -?\d+  Y: -?\d+",
        )
        window.document.dirty = False
        window.close()

    def test_mouse_position_uses_window_coordinates_in_window_mode(self) -> None:
        from window_auto.windowing.discovery import WindowInfo

        window = MainWindow()
        window.target_mode = RunMode.WINDOW
        window.selected_window = WindowInfo(
            hwnd=1,
            title="记事本",
            class_name="Notepad",
            window_width=800,
            window_height=600,
            client_width=800,
            client_height=600,
            visible=True,
            minimized=False,
            client_x=100,
            client_y=200,
        )

        with patch(
            "window_auto.gui.main_window.live_client_origin",
            return_value=(100, 200),
        ), patch(
            "window_auto.gui.main_window.QCursor.pos",
            return_value=QPoint(350, 500),
        ):
            window._update_mouse_position()

        self.assertEqual(window.mouse_position_label.text(), "窗口内 X: 250  Y: 300")

        window.target_mode = RunMode.FULLSCREEN
        with patch(
            "window_auto.gui.main_window.QCursor.pos",
            return_value=QPoint(350, 500),
        ):
            window._update_mouse_position()
        self.assertEqual(window.mouse_position_label.text(), "屏幕 X: 350  Y: 500")

        window.document.dirty = False
        window.close()

    def test_main_window_displays_startup_log(self) -> None:
        with TemporaryDirectory() as directory:
            startup_log = Path(directory) / "startup.log"
            startup_log.write_text(
                "[Window Auto] Starting...\n",
                encoding="utf-8",
            )
            with patch(
                "window_auto.gui.main_window.STARTUP_LOG_PATH",
                startup_log,
            ):
                window = MainWindow()

            self.assertIn(
                "启动 · [Window Auto] Starting...",
                window.log_view.toPlainText(),
            )
            window.close()

    def test_gui_opens_workflow_without_bound_target(self) -> None:
        with TemporaryDirectory() as directory:
            path = Path(directory) / "workflow.json"
            document = WorkflowDocument()
            document.add_step("wait")
            document.save(path)
            window = MainWindow()
            window.target_mode = RunMode.WINDOW
            window.selected_window = object()

            with patch(
                "window_auto.gui.main_window.QFileDialog.getOpenFileName",
                return_value=(str(path), "工作流 JSON (*.json)"),
            ):
                window.open_document()

            self.assertEqual(window.document.path, path.resolve())
            self.assertIsNone(window.selected_window)
            self.assertIn("未选择窗口", window.target_summary_label.text())
            window.close()

    def test_template_step_has_retry_buttons_and_parameter_help(self) -> None:
        window = MainWindow()
        window.palette.setCurrentRow(0)
        window.add_selected_action()

        retry_combo = next(
            control
            for control in window.properties.findChildren(QComboBox)
            if control.accessibleName() == "失败时"
        )
        retry_values = [
            retry_combo.itemData(index)
            for index in range(retry_combo.count())
        ]
        self.assertIn("retry", retry_values)
        self.assertIsNotNone(
            window.properties.findChild(QPushButton, "selectTemplateButton")
        )
        self.assertIsNotNone(
            window.properties.findChild(QPushButton, "createTemplateButton")
        )
        threshold_label = next(
            label
            for label in window.properties.findChildren(QLabel)
            if label.text() == "识别阈值："
        )
        self.assertIn("最低相似度", threshold_label.toolTip())

        post_action_combo = next(
            control
            for control in window.properties.findChildren(QComboBox)
            if control.accessibleName() == "识别后操作"
        )
        post_action_combo.setCurrentIndex(
            post_action_combo.findData("double_click")
        )
        QApplication.processEvents()
        visible_labels = {
            label.text()
            for label in window.properties.findChildren(QLabel)
        }
        self.assertIn("操作鼠标按键：", visible_labels)
        self.assertIn("双击间隔（毫秒）：", visible_labels)

        window.document.dirty = False
        window.close()

    def test_delay_relative_move_and_key_hold_fields_are_dynamic(self) -> None:
        window = MainWindow()

        window.palette.setCurrentRow(5)
        window.add_selected_action()
        delay_mode = next(
            control
            for control in window.properties.findChildren(QComboBox)
            if control.accessibleName() == "延迟方式"
        )
        delay_mode.setCurrentIndex(delay_mode.findData("random"))
        QApplication.processEvents()
        delay_labels = {
            label.text()
            for label in window.properties.findChildren(QLabel)
        }
        self.assertIn("最短延迟（毫秒）：", delay_labels)
        self.assertIn("最长延迟（毫秒）：", delay_labels)
        self.assertNotIn("固定延迟（毫秒）：", delay_labels)

        window.palette.setCurrentRow(1)
        window.add_selected_action()
        move_mode = next(
            control
            for control in window.properties.findChildren(QComboBox)
            if control.accessibleName() == "移动方式"
        )
        move_mode.setCurrentIndex(move_mode.findData("relative"))
        QApplication.processEvents()
        move_labels = {
            label.text()
            for label in window.properties.findChildren(QLabel)
        }
        self.assertIn("X 移动距离：", move_labels)
        self.assertIn("Y 移动距离：", move_labels)
        self.assertNotIn("X 坐标：", move_labels)

        window.palette.setCurrentRow(3)
        window.add_selected_action()
        key_labels = {
            label.text()
            for label in window.properties.findChildren(QLabel)
        }
        self.assertIn("按下持续（毫秒）：", key_labels)

        window.document.dirty = False
        window.close()

    def test_save_as_action_is_reachable_from_the_menu_bar(self) -> None:
        window = MainWindow()

        menu_actions = [
            action
            for menu in window.menuBar().actions()
            for action in menu.menu().actions()
        ]

        self.assertIn(window.save_as_action, menu_actions)
        window.document.dirty = False
        window.close()

    def test_run_workflow_step_has_file_picker(self) -> None:
        window = MainWindow()
        window.palette.setCurrentRow(6)
        window.add_selected_action()

        self.assertEqual(window.document.steps[0]["type"], "run_workflow")
        self.assertIsNotNone(
            window.properties.findChild(QPushButton, "selectWorkflowButton")
        )
        labels = {label.text() for label in window.properties.findChildren(QLabel)}
        self.assertIn("子工作流文件：", labels)

        window.document.dirty = False
        window.close()

    def test_ocr_step_has_retry_option_and_expected_text_field(self) -> None:
        window = MainWindow()
        window.palette.setCurrentRow(7)
        window.add_selected_action()

        self.assertEqual(window.document.steps[0]["type"], "ocr_match")
        retry_combo = next(
            control
            for control in window.properties.findChildren(QComboBox)
            if control.accessibleName() == "失败时"
        )
        retry_values = [
            retry_combo.itemData(index)
            for index in range(retry_combo.count())
        ]
        self.assertIn("retry", retry_values)
        labels = {label.text() for label in window.properties.findChildren(QLabel)}
        self.assertIn("期望文本：", labels)
        self.assertIn("识别后操作：", labels)

        post_action_combo = next(
            control
            for control in window.properties.findChildren(QComboBox)
            if control.accessibleName() == "识别后操作"
        )
        post_action_combo.setCurrentIndex(post_action_combo.findData("double_click"))
        QApplication.processEvents()
        visible_labels = {
            label.text()
            for label in window.properties.findChildren(QLabel)
        }
        self.assertIn("操作鼠标按键：", visible_labels)
        self.assertIn("双击间隔（毫秒）：", visible_labels)

        window.document.dirty = False
        window.close()

    def test_help_menu_offers_update_actions(self) -> None:
        with TemporaryDirectory() as directory:
            settings_path = str(Path(directory) / "settings.ini")

            def make_settings() -> QSettings:
                return QSettings(settings_path, QSettings.Format.IniFormat)

            with patch(
                "window_auto.gui.main_window.QSettings", side_effect=make_settings
            ):
                window = MainWindow()

                menu_titles = [
                    action.text() for action in window.menuBar().actions()
                ]
                self.assertIn("帮助(&H)", menu_titles)
                self.assertTrue(window.auto_update_action.isCheckable())
                self.assertTrue(window.auto_update_action.isChecked())

                window.auto_update_action.setChecked(False)
                self.assertFalse(window._auto_check_enabled())
                window.auto_update_action.setChecked(True)
                self.assertTrue(window._auto_check_enabled())

                # Building the window must not start any network request.
                self.assertIsNone(window._update_checker._reply)

                window.document.dirty = False
                window.close()

    def test_step_list_items_include_parameter_summary(self) -> None:
        window = MainWindow()
        window.palette.setCurrentRow(5)  # 延迟
        window.add_selected_action()

        text = window.step_list.item(0).text()

        self.assertIn("固定 500 毫秒", text)
        self.assertIn("延迟", text)
        window.document.dirty = False
        window.close()

    def test_summarize_step_describes_each_type(self) -> None:
        from window_auto.gui.step_list import summarize_step

        self.assertEqual(
            summarize_step({"type": "wait", "delay_mode": "fixed", "duration_ms": 500}),
            "固定 500 毫秒",
        )
        self.assertEqual(
            summarize_step(
                {
                    "type": "wait",
                    "delay_mode": "random",
                    "min_duration_ms": 100,
                    "max_duration_ms": 900,
                }
            ),
            "随机 100~900 毫秒",
        )
        self.assertEqual(
            summarize_step(
                {"type": "mouse_click", "x": 100, "y": 200, "button": "left", "count": 1}
            ),
            "左键点击 (100, 200)",
        )
        self.assertEqual(
            summarize_step(
                {"type": "mouse_click", "match_variable": "match", "button": "left", "count": 2}
            ),
            "左键双击 识别结果「match」",
        )
        self.assertEqual(
            summarize_step({"type": "key_press", "key": "S", "modifiers": ["CTRL"]}),
            "按键 Ctrl+S",
        )
        self.assertEqual(
            summarize_step({"type": "run_workflow", "workflow": "child.json"}),
            "子工作流 child.json",
        )
        self.assertEqual(
            summarize_step(
                {
                    "type": "ocr_match",
                    "expected": ["确定"],
                    "threshold": 0.3,
                    "post_action": "click",
                }
            ),
            "识别文字“确定” · 阈值 0.3 · 识别后单击",
        )
        sensitive = summarize_step(
            {"type": "text_input", "text": "secret", "sensitive": True}
        )
        self.assertIn("敏感内容", sensitive)
        self.assertNotIn("secret", sensitive)

    def test_key_picker_dialog_offers_full_keyboard_layout(self) -> None:
        from window_auto.gui.key_picker import KeyPickerDialog

        dialog = KeyPickerDialog("ENTER")
        buttons = dialog.findChildren(QPushButton)
        self.assertGreaterEqual(len(buttons), 100)

        button_a = next(button for button in buttons if button.text() == "A")
        button_a.click()

        self.assertEqual(dialog.selected_value(), "A")
        self.assertEqual(dialog.result(), QDialog.DialogCode.Accepted)
        dialog.close()

    def test_key_display_label_covers_names_codes_and_fallback(self) -> None:
        from window_auto.gui.key_picker import key_display_label

        self.assertEqual(key_display_label("ENTER"), "Enter")
        self.assertEqual(key_display_label("S"), "S")
        self.assertEqual(key_display_label(20), "Caps")
        self.assertEqual(key_display_label(99), "Num 3")
        self.assertEqual(key_display_label(200), "200")

    def test_key_press_step_uses_readonly_field_with_picker_button(self) -> None:
        window = MainWindow()
        window.palette.setCurrentRow(3)
        window.add_selected_action()

        editor = window.properties.findChild(QLineEdit, "keyValueEdit")
        self.assertIsNotNone(editor)
        self.assertTrue(editor.isReadOnly())
        self.assertEqual(editor.text(), "Enter")
        self.assertIsNotNone(
            window.properties.findChild(QPushButton, "selectKeyButton")
        )
        window.document.dirty = False
        window.close()

    def test_key_picker_selection_updates_step_value(self) -> None:
        from window_auto.gui.key_picker import KeyPickerDialog

        window = MainWindow()
        window.palette.setCurrentRow(3)
        window.add_selected_action()
        button = window.properties.findChild(QPushButton, "selectKeyButton")

        with patch.object(
            KeyPickerDialog, "exec", return_value=QDialog.DialogCode.Accepted
        ), patch.object(KeyPickerDialog, "selected_value", return_value="F5"):
            button.click()

        self.assertEqual(window.document.steps[0]["key"], "F5")
        editor = window.properties.findChild(QLineEdit, "keyValueEdit")
        self.assertEqual(editor.text(), "F5")
        window.document.dirty = False
        window.close()

    def test_numeric_virtual_key_codes_parse_to_integers(self) -> None:
        self.assertEqual(PropertyEditor._parse_text("65", "ENTER", "key"), 65)
        self.assertEqual(PropertyEditor._parse_text("ENTER", "ENTER", "key"), "ENTER")
        self.assertEqual(
            PropertyEditor._parse_text("CTRL, 16", [], "modifiers"),
            ["CTRL", 16],
        )
        self.assertEqual(
            PropertyEditor._parse_text("65", "ENTER", "post_key"),
            65,
        )

    def test_exotic_unicode_digit_does_not_crash_key_parsing(self) -> None:
        self.assertEqual(PropertyEditor._parse_text("²", "ENTER", "key"), "²")
        self.assertEqual(
            PropertyEditor._parse_text("CTRL, ²", [], "modifiers"),
            ["CTRL", "²"],
        )

    def test_failure_popup_is_not_swallowed_by_step_name_text(self) -> None:
        window = MainWindow()
        window._worker = None  # no worker: nothing was cancelled
        calls = []
        with patch.object(QMessageBox, "critical", lambda *a, **k: calls.append(a)):
            window.on_workflow_finished(False, "Step '已停止检查' failed: boom")
        self.assertEqual(len(calls), 1)

        worker = type(
            "Worker",
            (),
            {"cancellation": type("Token", (), {"cancelled": True})()},
        )()
        window._worker = worker
        with patch.object(QMessageBox, "critical", lambda *a, **k: calls.append(a)):
            window.on_workflow_finished(False, "工作流已停止。")
        self.assertEqual(len(calls), 1)  # still exactly one: the real failure above
        window._worker = None
        window.document.dirty = False
        window.close()

    def test_window_filter_edits_refresh_immediately(self) -> None:
        from window_auto.gui.window_dialog import WindowSelectorDialog
        from window_auto.windowing.discovery import WindowInfo

        fake = WindowInfo(
            hwnd=0x1001, title="记事本", class_name="Notepad",
            window_width=800, window_height=600,
            client_width=800, client_height=600,
            visible=True, minimized=False,
        )
        with patch(
            "window_auto.gui.window_dialog.list_windows", return_value=[fake]
        ) as mocked_list:
            dialog = WindowSelectorDialog()
            calls_after_init = mocked_list.call_count
            dialog.filter_edit.setText("记")
            calls_after_typing = mocked_list.call_count
            dialog.visible_only.setChecked(False)
            calls_after_toggle = mocked_list.call_count
            dialog.reject()

        self.assertGreater(calls_after_typing, calls_after_init)
        self.assertGreater(calls_after_toggle, calls_after_typing)
    def test_run_settings_persist_mode_and_profile(self) -> None:
        with TemporaryDirectory() as directory:
            settings_path = str(Path(directory) / "settings.ini")

            def make_settings() -> QSettings:
                return QSettings(settings_path, QSettings.Format.IniFormat)

            with patch(
                "window_auto.gui.main_window.QSettings", side_effect=make_settings
            ):
                window = MainWindow()

                self.assertEqual(window.target_mode, RunMode.WINDOW)
                self.assertEqual(
                    window.input_profile_name, InputProfileName.FOREGROUND_PRECISE
                )

                window.target_mode = RunMode.FULLSCREEN
                window.input_profile_name = InputProfileName.FOREGROUND_COMPATIBLE
                window._persist_run_settings()
                self.assertEqual(make_settings().value("run/target_mode"), "fullscreen")
                self.assertEqual(
                    make_settings().value("run/input_profile"),
                    "foreground-compatible",
                )

                rebuilt = MainWindow()
                self.assertEqual(rebuilt.target_mode, RunMode.FULLSCREEN)
                self.assertEqual(
                    rebuilt.input_profile_name, InputProfileName.FOREGROUND_COMPATIBLE
                )

                rebuilt.document.dirty = False
                rebuilt.close()
                window.document.dirty = False
                window.close()

    def test_apply_mode_overrides_controller_config(self) -> None:
        window = MainWindow()

        window.target_mode = RunMode.FULLSCREEN
        fullscreen_config = {"controller": {"screencap_mode": "background"}}
        window._apply_mode_overrides(fullscreen_config)
        self.assertEqual(
            fullscreen_config["controller"]["screencap_mode"], "foreground"
        )
        self.assertEqual(fullscreen_config["controller"]["capture_scope"], "desktop")
        self.assertEqual(
            fullscreen_config["controller"]["foreground_screencap"],
            ["DXGI_DesktopDup", "ScreenDC"],
        )

        window.target_mode = RunMode.WINDOW
        window_config = {"controller": {"screencap_mode": "foreground"}}
        window._apply_mode_overrides(window_config)
        self.assertEqual(window_config["controller"]["screencap_mode"], "background")
        self.assertEqual(window_config["controller"]["capture_scope"], "window")

        window.document.dirty = False
        window.close()

    def test_run_settings_dialog_filters_profiles_by_mode(self) -> None:
        dialog = RunSettingsDialog(
            RunMode.WINDOW, None, InputProfileName.FOREGROUND_PRECISE
        )
        self.assertTrue(dialog.select_window_button.isEnabled())
        self.assertTrue(dialog.clear_window_button.isHidden())
        self.assertEqual(dialog.profile_combo.count(), 5)

        dialog._mode_radios[RunMode.FULLSCREEN].click()
        self.assertTrue(dialog.select_window_button.isEnabled())
        self.assertEqual(
            [
                dialog.profile_combo.itemData(index)
                for index in range(dialog.profile_combo.count())
            ],
            [InputProfileName.FOREGROUND_COMPATIBLE, InputProfileName.DRIVER_INTERCEPTION],
        )
        self.assertEqual(dialog.result_mode, RunMode.FULLSCREEN)
        self.assertEqual(dialog.result_profile, InputProfileName.FOREGROUND_COMPATIBLE)
        self.assertIn("未绑定", dialog.window_label.text())

        dialog._mode_radios[RunMode.WINDOW].click()
        self.assertEqual(dialog.profile_combo.count(), 5)
        dialog.reject()
        dialog.close()

    def test_run_settings_dialog_fullscreen_window_binding_is_optional(self) -> None:
        from window_auto.windowing.discovery import WindowInfo

        bound = WindowInfo(
            hwnd=0x1234,
            title="游戏大厅",
            class_name="GameWindow",
            window_width=1920,
            window_height=1080,
            client_width=1920,
            client_height=1080,
            visible=True,
            minimized=False,
        )
        dialog = RunSettingsDialog(
            RunMode.FULLSCREEN, bound, InputProfileName.FOREGROUND_COMPATIBLE
        )
        self.assertIn("游戏大厅", dialog.window_label.text())
        self.assertFalse(dialog.clear_window_button.isHidden())

        dialog.clear_window_button.click()
        self.assertIsNone(dialog.selected_window)
        self.assertIn("未绑定", dialog.window_label.text())
        self.assertTrue(dialog.clear_window_button.isHidden())

        dialog._mode_radios[RunMode.WINDOW].click()
        self.assertIn("未选择", dialog.window_label.text())
        self.assertTrue(dialog.clear_window_button.isHidden())

        dialog.reject()
        dialog.close()

    def test_window_mode_requires_window_but_fullscreen_does_not(self) -> None:
        from window_auto.windowing.discovery import WindowInfo

        window = MainWindow()
        window.target_mode = RunMode.WINDOW
        window.selected_window = None
        with patch.object(QMessageBox, "information") as info:
            window.run_workflow()
        info.assert_called_once()

        window.target_mode = RunMode.FULLSCREEN
        fake_window = WindowInfo(
            hwnd=1,
            title="整个屏幕",
            class_name="",
            window_width=1920,
            window_height=1080,
            client_width=1920,
            client_height=1080,
            visible=True,
            minimized=False,
            client_x=0,
            client_y=0,
        )
        window.document.dirty = True
        with (
            patch.object(QMessageBox, "information") as info,
            patch(
                "window_auto.gui.main_window.desktop_window_info",
                return_value=fake_window,
            ),
            patch.object(MainWindow, "save_document", return_value=False),
        ):
            window.run_workflow()
        info.assert_not_called()
        window.document.dirty = False
        window.close()

    def test_target_summary_reflects_mode_and_window(self) -> None:
        window = MainWindow()
        window.target_mode = RunMode.WINDOW
        window._refresh_target_summary()
        self.assertIn("未选择窗口", window.target_summary_label.text())

        window.target_mode = RunMode.FULLSCREEN
        window._refresh_target_summary()
        self.assertIn("整个屏幕", window.target_summary_label.text())

        window.document.dirty = False
        window.close()

    def test_foreground_bound_window_only_runs_in_fullscreen_with_binding(self) -> None:
        from window_auto.windowing.discovery import WindowInfo

        bound = WindowInfo(
            hwnd=0x1234,
            title="游戏大厅",
            class_name="GameWindow",
            window_width=1920,
            window_height=1080,
            client_width=1920,
            client_height=1080,
            visible=True,
            minimized=False,
        )
        window = MainWindow()

        window.target_mode = RunMode.WINDOW
        window.selected_window = bound
        with patch("window_auto.gui.main_window.foreground_window") as foreground:
            self.assertTrue(window._foreground_bound_window())
        foreground.assert_not_called()

        window.target_mode = RunMode.FULLSCREEN
        window.selected_window = None
        with patch("window_auto.gui.main_window.foreground_window") as foreground:
            self.assertTrue(window._foreground_bound_window())
        foreground.assert_not_called()

        window.selected_window = bound
        with patch("window_auto.gui.main_window.foreground_window") as foreground:
            self.assertTrue(window._foreground_bound_window())
        foreground.assert_called_once_with(bound)

        with patch(
            "window_auto.gui.main_window.foreground_window",
            side_effect=DirectInputError("置顶窗口已关闭或不存在，请在运行设置中重新绑定。"),
        ), patch.object(QMessageBox, "warning") as warning:
            self.assertFalse(window._foreground_bound_window())
        warning.assert_called_once()

        window.document.dirty = False
        window.close()

    def test_run_settings_action_is_reachable_from_the_menu_bar(self) -> None:
        window = MainWindow()

        menu_titles = [action.text() for action in window.menuBar().actions()]
        self.assertIn("运行(&R)", menu_titles)
        menu_actions = [
            action
            for menu in window.menuBar().actions()
            for action in menu.menu().actions()
        ]
        self.assertIn(window.run_settings_action, menu_actions)
        self.assertIn(window.run_action, menu_actions)
        self.assertIn(window.stop_action, menu_actions)

        window.document.dirty = False
        window.close()

    def test_update_request_uses_valid_redirect_policy(self) -> None:
        from PySide6.QtNetwork import QNetworkRequest
        from window_auto.gui.update_checker import _build_request

        request = _build_request("https://api.github.com/example", 1000)

        self.assertEqual(
            request.attribute(QNetworkRequest.Attribute.RedirectPolicyAttribute),
            QNetworkRequest.RedirectPolicy.NoLessSafeRedirectPolicy,
        )
        self.assertEqual(request.transferTimeout(), 1000)


if __name__ == "__main__":
    unittest.main()
