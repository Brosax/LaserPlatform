"""Utilities for PyInstaller frozen-app compatibility."""

import sys
from pathlib import Path


def is_frozen() -> bool:
    """True when running inside a PyInstaller bundle."""
    return getattr(sys, "frozen", False)


def resource_path(relative: str) -> Path:
    """Resolve a path to a bundled resource.

    In development: relative to the project root.
    In frozen app: relative to sys._MEIPASS (the temp extraction dir).
    """
    if is_frozen():
        base = Path(sys._MEIPASS)  # type: ignore[attr-defined]
    else:
        base = Path(__file__).resolve().parents[1]
    return base / relative
