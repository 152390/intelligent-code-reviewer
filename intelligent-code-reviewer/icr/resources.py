"""Locate bundled files both when running from source and inside the PyInstaller executable."""
from __future__ import annotations
import os
import sys

FROZEN = getattr(sys, "frozen", False)


def resource_path(*parts: str) -> str:
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    return os.path.join(base, *parts)


def app_data_dir() -> str:
    """Per-user folder for settings and logs (e.g. C:\\Users\\<you>\\.icr_reviewer)."""
    d = os.path.join(os.path.expanduser("~"), ".icr_reviewer")
    os.makedirs(d, exist_ok=True)
    return d
