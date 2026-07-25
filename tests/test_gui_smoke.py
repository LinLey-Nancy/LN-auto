import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QComboBox, QLabel, QMessageBox, QPushButton

from nzm_auto.gui.app import create_application
from nzm_auto.gui.document import WorkflowDocument
from nzm_auto.gui.main_window import MainWindow


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

    def test_main_window_displays_startup_log(self) -> None:
        with TemporaryDirectory() as directory:
            startup_log = Path(directory) / "startup.log"
            startup_log.write_text(
                "[NZM Auto] Starting...\n",
                encoding="utf-8",
            )
            with patch(
                "nzm_auto.gui.main_window.STARTUP_LOG_PATH",
                startup_log,
            ):
                window = MainWindow()

            self.assertIn(
                "启动 · [NZM Auto] Starting...",
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
                "nzm_auto.gui.main_window.QFileDialog.getOpenFileName",
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


if __name__ == "__main__":
    unittest.main()
