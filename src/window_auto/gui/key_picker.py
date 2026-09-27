"""Click-to-pick keyboard layout dialog for choosing a virtual key."""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)


_KEY_SIZE = 44
_KEY_SPACING = 4
_SCALE = 4  # grid columns per single-width key

_NAME_LABELS = {
    "ESC": "Esc",
    "ENTER": "Enter",
    "RETURN": "Enter",
    "BACKSPACE": "Backspace",
    "TAB": "Tab",
    "SPACE": "Space",
    "SHIFT": "Shift",
    "CTRL": "Ctrl",
    "CONTROL": "Ctrl",
    "ALT": "Alt",
    "INSERT": "Ins",
    "DELETE": "Del",
    "HOME": "Home",
    "END": "End",
    "PAGEUP": "PgUp",
    "PAGEDOWN": "PgDn",
    "UP": "↑",
    "DOWN": "↓",
    "LEFT": "←",
    "RIGHT": "→",
}

_VK_LABELS = {
    19: "Pause",
    20: "Caps",
    44: "PrtSc",
    91: "Win",
    92: "Win",
    93: "Menu",
    96: "Num 0",
    97: "Num 1",
    98: "Num 2",
    99: "Num 3",
    100: "Num 4",
    101: "Num 5",
    102: "Num 6",
    103: "Num 7",
    104: "Num 8",
    105: "Num 9",
    106: "Num *",
    107: "Num +",
    109: "Num -",
    110: "Num .",
    111: "Num /",
    144: "Num",
    145: "ScrLk",
    186: ";",
    187: "=",
    188: ",",
    189: "-",
    190: ".",
    191: "/",
    192: "`",
    219: "[",
    220: "\\",
    221: "]",
    222: "'",
}


def key_display_label(value: Any) -> str:
    """Human-readable label for a stored key name or virtual-key code."""
    if isinstance(value, str):
        text = value.strip()
        if len(text) == 1:
            return text
        return _NAME_LABELS.get(text.upper(), text)
    if isinstance(value, bool):
        return str(value)
    if isinstance(value, int):
        return _VK_LABELS.get(value, str(value))
    return str(value)


def _letters(row: str) -> list[tuple[str, str, float]]:
    return [(letter, letter, 1.0) for letter in row]


# Entries are (label, stored value, width in key units); None is a one-unit gap.
_FUNCTION_ROW: list[tuple[str, str | int, float] | None] = [
    ("Esc", "ESC", 1.0),
    None,
    *[("F%d" % number, "F%d" % number, 1.0) for number in range(1, 5)],
    None,
    *[("F%d" % number, "F%d" % number, 1.0) for number in range(5, 9)],
    None,
    *[("F%d" % number, "F%d" % number, 1.0) for number in range(9, 13)],
]

_MAIN_ROWS: list[list[tuple[str, str | int, float] | None]] = [
    [
        ("`", 192, 1.0),
        *[(digit, digit, 1.0) for digit in "1234567890"],
        ("-", 189, 1.0),
        ("=", 187, 1.0),
        ("Backspace", "BACKSPACE", 2.0),
    ],
    [
        ("Tab", "TAB", 1.5),
        *_letters("QWERTYUIOP"),
        ("[", 219, 1.0),
        ("]", 221, 1.0),
        ("\\", 220, 1.5),
    ],
    [
        ("Caps", 20, 1.75),
        *_letters("ASDFGHJKL"),
        (";", 186, 1.0),
        ("'", 222, 1.0),
        ("Enter", "ENTER", 2.25),
    ],
    [
        ("Shift", "SHIFT", 2.25),
        *_letters("ZXCVBNM"),
        (",", 188, 1.0),
        (".", 190, 1.0),
        ("/", 191, 1.0),
        ("Shift", "SHIFT", 2.75),
    ],
    [
        ("Ctrl", "CTRL", 1.25),
        ("Win", 91, 1.25),
        ("Alt", "ALT", 1.25),
        ("Space", "SPACE", 6.25),
        ("Alt", "ALT", 1.25),
        ("Win", 92, 1.25),
        ("Menu", 93, 1.25),
        ("Ctrl", "CTRL", 1.25),
    ],
]

_NAV_ROWS: list[list[tuple[str, str | int, float] | None]] = [
    [("PrtSc", 44, 1.0), ("ScrLk", 145, 1.0), ("Pause", 19, 1.0)],
    [],
    [("Ins", "INSERT", 1.0), ("Home", "HOME", 1.0), ("PgUp", "PAGEUP", 1.0)],
    [("Del", "DELETE", 1.0), ("End", "END", 1.0), ("PgDn", "PAGEDOWN", 1.0)],
    [],
    [None, ("↑", "UP", 1.0), None],
    [("←", "LEFT", 1.0), ("↓", "DOWN", 1.0), ("→", "RIGHT", 1.0)],
]


def _values_match(candidate: str | int, current: Any) -> bool:
    if isinstance(candidate, str) and isinstance(current, str):
        return candidate.strip().upper() == current.strip().upper()
    return candidate == current


class KeyPickerDialog(QDialog):
    """Full-size keyboard layout; clicking a key selects it and closes."""

    def __init__(
        self, current: str | int | None = None, parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("选择按键")
        self.setModal(True)
        self._current = current
        self._selected: str | int | None = None

        main_grid = QGridLayout()
        main_grid.setSpacing(_KEY_SPACING)
        self._place_row(main_grid, 0, _FUNCTION_ROW)
        main_grid.setRowMinimumHeight(1, 12)
        for offset, row_entries in enumerate(_MAIN_ROWS):
            self._place_row(main_grid, 2 + offset, row_entries)

        nav_grid = QGridLayout()
        nav_grid.setSpacing(_KEY_SPACING)
        for row_index, row_entries in enumerate(_NAV_ROWS):
            if not row_entries:
                nav_grid.setRowMinimumHeight(row_index, 12 if row_index == 1 else 0)
                continue
            self._place_row(nav_grid, row_index, row_entries)

        numpad_grid = QGridLayout()
        numpad_grid.setSpacing(_KEY_SPACING)
        self._build_numpad(numpad_grid)

        boards = QHBoxLayout()
        boards.addLayout(main_grid)
        boards.addSpacing(18)
        boards.addLayout(nav_grid)
        boards.addSpacing(18)
        boards.addLayout(numpad_grid)
        boards.addStretch(1)
        for grid in (main_grid, nav_grid, numpad_grid):
            boards.setAlignment(grid, Qt.AlignmentFlag.AlignTop)

        hint = QLabel("点击上方按键完成选择，按 Esc 取消。")
        hint.setObjectName("mutedLabel")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.addLayout(boards)
        layout.addSpacing(10)
        layout.addWidget(hint)

    def selected_value(self) -> str | int | None:
        return self._selected

    def _place_row(
        self,
        grid: QGridLayout,
        row: int,
        entries: list[tuple[str, str | int, float] | None],
    ) -> None:
        column = 0
        for entry in entries:
            if entry is None:
                column += _SCALE
                continue
            label, value, width = entry
            span = int(round(width * _SCALE))
            grid.addWidget(self._make_key(label, value, width), row, column, 1, span)
            column += span

    def _build_numpad(self, grid: QGridLayout) -> None:
        for column, entry in enumerate(
            [("Num", 144), ("/", 111), ("*", 106), ("-", 109)]
        ):
            grid.addWidget(self._make_key(entry[0], entry[1], 1.0), 0, column)
        digits = [
            ("7", 103), ("8", 104), ("9", 105),
            ("4", 100), ("5", 101), ("6", 102),
            ("1", 97), ("2", 98), ("3", 99),
        ]
        for index, (label, value) in enumerate(digits):
            grid.addWidget(
                self._make_key(label, value, 1.0), 1 + index // 3, index % 3
            )
        plus = self._make_key("+", 107, 1.0)
        plus.setMinimumHeight(_KEY_SIZE * 2 + _KEY_SPACING)
        grid.addWidget(plus, 1, 3, 2, 1)
        enter = self._make_key("Enter", "ENTER", 1.0)
        enter.setMinimumHeight(_KEY_SIZE * 2 + _KEY_SPACING)
        grid.addWidget(enter, 3, 3, 2, 1)
        zero = self._make_key("0", 96, 2.0)
        grid.addWidget(zero, 4, 0, 1, 2)
        grid.addWidget(self._make_key(".", 110, 1.0), 4, 2)

    def _make_key(self, label: str, value: str | int, width: float) -> QPushButton:
        button = QPushButton(label)
        button.setObjectName("keyboardKey")
        button.setMinimumSize(
            int(_KEY_SIZE * width + _KEY_SPACING * max(0.0, width - 1.0)),
            _KEY_SIZE,
        )
        button.setToolTip(f"选择按键 {label}")
        button.clicked.connect(lambda _checked=False, picked=value: self._pick(picked))
        if self._current is not None and _values_match(value, self._current):
            button.setStyleSheet(
                "background: #312E81; border: 2px solid #A78BFA; font-weight: 600;"
            )
        return button

    def _pick(self, value: str | int) -> None:
        self._selected = value
        self.accept()
