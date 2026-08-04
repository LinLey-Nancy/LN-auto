"""Minimal MaaFramework runtime checks.

This module deliberately does not create a controller, enumerate windows, or
send input. It only verifies that the bundled MaaFramework native library can
be loaded by the official Python binding.
"""

from __future__ import annotations


def get_maa_version() -> str:
    try:
        from maa.library import Library
    except (ImportError, OSError) as error:
        raise RuntimeError(f"MaaFramework Python binding failed to load: {error}") from error

    try:
        return Library.version()
    except OSError as error:
        raise RuntimeError(f"MaaFramework native library failed to load: {error}") from error
