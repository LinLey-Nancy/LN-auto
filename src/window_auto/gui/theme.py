"""Semantic dark theme for the Window Auto desktop editor."""

APP_STYLE = """
QWidget {
    background: #0F172A;
    color: #F8FAFC;
    font-size: 13px;
}
QMainWindow, QDialog { background: #0F172A; }
QToolBar {
    background: #111827;
    border: none;
    border-bottom: 1px solid #334155;
    spacing: 8px;
    padding: 8px;
}
QToolButton, QPushButton {
    background: #1E293B;
    border: 1px solid #475569;
    border-radius: 6px;
    min-height: 32px;
    padding: 4px 12px;
}
QToolButton:hover, QPushButton:hover { background: #334155; border-color: #64748B; }
QToolButton:pressed, QPushButton:pressed { background: #475569; }
QToolButton:focus, QPushButton:focus, QLineEdit:focus, QComboBox:focus,
QSpinBox:focus, QDoubleSpinBox:focus, QListWidget:focus, QTableWidget:focus {
    border: 2px solid #A78BFA;
}
QPushButton#primaryButton {
    background: #7C3AED;
    border-color: #8B5CF6;
    color: #FFFFFF;
    font-weight: 600;
}
QPushButton#dangerButton { background: #7F1D1D; border-color: #DC2626; }
QPushButton:disabled, QToolButton:disabled { color: #64748B; background: #172033; }
QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox, QPlainTextEdit {
    background: #111827;
    border: 1px solid #475569;
    border-radius: 5px;
    min-height: 30px;
    padding: 3px 8px;
    selection-background-color: #7C3AED;
}
QListWidget, QTableWidget {
    background: #111827;
    alternate-background-color: #172033;
    border: 1px solid #334155;
    border-radius: 6px;
    outline: none;
}
QListWidget::item { min-height: 38px; padding: 4px 8px; }
QListWidget::item:selected, QTableWidget::item:selected {
    background: #312E81;
    color: #FFFFFF;
}
QHeaderView::section {
    background: #1E293B;
    color: #CBD5E1;
    border: none;
    border-right: 1px solid #334155;
    border-bottom: 1px solid #334155;
    padding: 7px;
}
QGroupBox {
    border: 1px solid #334155;
    border-radius: 7px;
    margin-top: 12px;
    padding-top: 12px;
    font-weight: 600;
}
QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 4px; }
QLabel#sectionTitle { font-size: 15px; font-weight: 600; color: #FFFFFF; }
QLabel#mutedLabel { color: #94A3B8; }
QStatusBar { background: #111827; color: #CBD5E1; border-top: 1px solid #334155; }
QSplitter::handle { background: #334155; width: 1px; }
QDockWidget::title { background: #1E293B; padding: 7px; }
QScrollBar:vertical { background: #111827; width: 12px; }
QScrollBar::handle:vertical { background: #475569; border-radius: 5px; min-height: 24px; }
"""
