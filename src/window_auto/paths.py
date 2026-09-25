"""Resolve the project root for source checkouts and frozen builds."""

from __future__ import annotations

from pathlib import Path
import sys


def project_root() -> Path:
    """Return the directory that holds ``config/`` and ``assets/``.

    In a PyInstaller bundle those resources live in the application's internal
    data directory; in a source checkout they live at the repository root.
    """
    frozen_root = getattr(sys, "_MEIPASS", None)
    if frozen_root is not None:
        return Path(frozen_root)
    return Path(__file__).resolve().parents[2]
