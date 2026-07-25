"""Desktop application entry point."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from PySide6.QtGui import QFont, QFontDatabase
from PySide6.QtCore import QLibraryInfo, QTimer, QTranslator
from PySide6.QtWidgets import QApplication

from nzm_auto.gui.main_window import MainWindow
from nzm_auto.gui.theme import APP_STYLE


def install_chinese_translations(app: QApplication) -> bool:
    """Load Qt's bundled Simplified Chinese text for standard dialogs/buttons."""
    translator = QTranslator(app)
    translations_path = QLibraryInfo.path(
        QLibraryInfo.LibraryPath.TranslationsPath
    )
    if not translator.load("qtbase_zh_CN", translations_path):
        return False
    app.installTranslator(translator)
    app._nzm_qt_translator = translator
    return True


def create_application(argv: list[str] | None = None) -> QApplication:
    app = QApplication(argv if argv is not None else sys.argv)
    install_chinese_translations(app)
    app.setApplicationName("NZM Auto")
    app.setOrganizationName("NZM Auto")
    app.setStyle("Fusion")
    font_path = Path(r"C:\Windows\Fonts\msyh.ttc")
    if font_path.is_file():
        font_id = QFontDatabase.addApplicationFont(str(font_path))
        families = QFontDatabase.applicationFontFamilies(font_id)
        if families:
            app.setFont(QFont(families[0], 10))
    app.setStyleSheet(APP_STYLE)
    return app


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="nzm-auto-gui")
    parser.add_argument(
        "--smoke-test",
        action="store_true",
        help="Create the main window and exit automatically after startup validation.",
    )
    args = parser.parse_args(sys.argv[1:] if argv is None else argv)
    app = create_application([sys.argv[0]])
    window = MainWindow()
    window.show()
    if args.smoke_test:
        QTimer.singleShot(100, app.quit)
    return app.exec()
