"""Resolve the running application version.

Resolution order:
1. ``version.txt`` next to the bundled resources — written by
   ``scripts/build_installer.py`` from pyproject.toml at build time, so a frozen
   build always reports the exact release version.
2. Installed package metadata (editable or regular installs).
3. The ``__version__`` constant as a last resort.
"""

from __future__ import annotations

import importlib.metadata

from window_auto import __version__
from window_auto.paths import project_root


def current_version() -> str:
    version_file = project_root() / "version.txt"
    try:
        if version_file.is_file():
            text = version_file.read_text(encoding="utf-8").strip()
            if text:
                return text
    except OSError:
        pass
    try:
        return importlib.metadata.version("LN-auto")
    except importlib.metadata.PackageNotFoundError:
        return __version__
