"""Resolve friendly key names to Windows virtual-key codes."""

from __future__ import annotations


NAMED_KEYS = {
    "BACKSPACE": 0x08,
    "TAB": 0x09,
    "ENTER": 0x0D,
    "RETURN": 0x0D,
    "SHIFT": 0x10,
    "CTRL": 0x11,
    "CONTROL": 0x11,
    "ALT": 0x12,
    "ESC": 0x1B,
    "ESCAPE": 0x1B,
    "SPACE": 0x20,
    "PAGEUP": 0x21,
    "PAGEDOWN": 0x22,
    "END": 0x23,
    "HOME": 0x24,
    "LEFT": 0x25,
    "UP": 0x26,
    "RIGHT": 0x27,
    "DOWN": 0x28,
    "INSERT": 0x2D,
    "DELETE": 0x2E,
}
NAMED_KEYS.update({f"F{number}": 0x6F + number for number in range(1, 13)})

_UNSHIFTED_TEXT_KEYS = {
    " ": 0x20,
    "\t": 0x09,
    "\n": 0x0D,
    "\r": 0x0D,
    "-": 0xBD,
    "=": 0xBB,
    "[": 0xDB,
    "]": 0xDD,
    "\\": 0xDC,
    ";": 0xBA,
    "'": 0xDE,
    ",": 0xBC,
    ".": 0xBE,
    "/": 0xBF,
    "`": 0xC0,
}
_SHIFTED_TEXT_KEYS = {
    "_": 0xBD,
    "+": 0xBB,
    "{": 0xDB,
    "}": 0xDD,
    "|": 0xDC,
    ":": 0xBA,
    '"': 0xDE,
    "<": 0xBC,
    ">": 0xBE,
    "?": 0xBF,
    "~": 0xC0,
}
_SHIFTED_TEXT_KEYS.update(
    dict(zip(")!@#$%^&*(", (ord(value) for value in "0123456789"), strict=True))
)


def resolve_virtual_key(value: str | int) -> int:
    if isinstance(value, bool):
        raise ValueError("Boolean values are not valid virtual-key codes.")
    if isinstance(value, int):
        if 1 <= value <= 0xFF:
            return value
        raise ValueError(f"Virtual-key code must be from 1 to 255: {value}.")

    normalized = value.strip().upper()
    if len(normalized) == 1 and ("A" <= normalized <= "Z" or "0" <= normalized <= "9"):
        return ord(normalized)
    try:
        return NAMED_KEYS[normalized]
    except KeyError as error:
        raise ValueError(f"Unknown virtual key name: {value!r}.") from error


def resolve_text_character(value: str) -> tuple[int, bool]:
    """Return ``(virtual_key, shift_required)`` for one US-layout ASCII character."""
    if len(value) != 1:
        raise ValueError("Text key resolution requires exactly one character.")
    if "a" <= value <= "z":
        return ord(value.upper()), False
    if "A" <= value <= "Z":
        return ord(value), True
    if "0" <= value <= "9":
        return ord(value), False
    if value in _UNSHIFTED_TEXT_KEYS:
        return _UNSHIFTED_TEXT_KEYS[value], False
    if value in _SHIFTED_TEXT_KEYS:
        return _SHIFTED_TEXT_KEYS[value], True
    raise ValueError(
        f"Character {value!r} cannot be emitted by key_sequence; use direct text input."
    )
