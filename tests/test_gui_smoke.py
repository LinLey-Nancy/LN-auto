import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QComboBox, QLabel, QMessageBox, QPushButton

from window_auto.gui.app import create_application
from window_auto.gui.document import WorkflowDocument
from window_auto.gui.main_window import MainWindow
from window_auto.gui.property_editor import PropertyEditor


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

        self.assertEqual(window.palette.count(), 6)
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
            r"鼠标 X: -?\d+  Y: -?\d+",
        )
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
            window.selected_window = object()
            window.target_label.setText("旧目标窗口")

            with patch(
                "window_auto.gui.main_window.QFileDialog.getOpenFileName",
                return_value=(str(path), "工作流 JSON (*.json)"),
            ):
                window.open_document()

            self.assertEqual(window.document.path, path.resolve())
            self.assertIsNone(window.selected_window)
            self.assertEqual(window.target_label.text(), "未选择目标窗口")
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


if __name__ == "__main__":
    unittest.main()
