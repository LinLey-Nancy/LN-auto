import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PIL import Image
from PySide6.QtCore import QRect, QSize
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QApplication

from nzm_auto.gui.template_creator import (
    TemplateCreationDialog,
    map_selection_to_source,
    safe_template_stem,
    scale_crop_to_recognition,
    unique_template_path,
)


class TemplateCreatorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def test_name_and_unique_path_do_not_overwrite_existing_template(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "target.png").touch()

            output = unique_template_path(root, " target?.png ")

            self.assertEqual(safe_template_stem(" target? "), "target")
            self.assertEqual(output.name, "target-2.png")

    def test_selection_maps_to_original_image_size(self) -> None:
        mapped = map_selection_to_source(
            QRect(10, 5, 20, 10),
            QSize(100, 50),
            QSize(200, 100),
        )

        self.assertEqual(mapped, QRect(20, 10, 40, 20))

    def test_dialog_crops_and_saves_png_to_template_directory(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "screen.png"
            templates = root / "templates"
            Image.new("RGB", (100, 50), (30, 80, 120)).save(source)
            dialog = TemplateCreationDialog(source, templates)
            dialog.name_edit.setText("created")
            dialog.selector._selection = QRect(10, 5, 20, 10)

            dialog._save_template()

            self.assertEqual(dialog.saved_path, (templates / "created.png").resolve())
            with Image.open(dialog.saved_path) as image:
                self.assertEqual(image.size, (20, 10))
            dialog.close()

    def test_crop_scales_to_recognition_size(self) -> None:
        with TemporaryDirectory() as directory:
            source = Path(directory) / "screen.png"
            Image.new("RGB", (200, 100), (30, 80, 120)).save(source)
            cropped = QPixmap(str(source)).copy(QRect(20, 10, 40, 20))

            scaled = scale_crop_to_recognition(
                cropped,
                QSize(200, 100),
                QSize(100, 50),
            )

            self.assertEqual(scaled.size(), QSize(20, 10))

    def test_dialog_saves_template_at_recognition_size(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "screen.png"
            templates = root / "templates"
            Image.new("RGB", (200, 100), (30, 80, 120)).save(source)
            dialog = TemplateCreationDialog(
                source,
                templates,
                recognition_size=QSize(100, 50),
            )
            dialog.name_edit.setText("scaled")
            dialog.selector._selection = QRect(20, 10, 40, 20)

            dialog._save_template()

            self.assertTrue(dialog.normalized_for_recognition)
            with Image.open(dialog.saved_path) as image:
                self.assertEqual(image.size, (20, 10))
            dialog.close()


if __name__ == "__main__":
    unittest.main()
