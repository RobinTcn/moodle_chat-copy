"""Utility functions for backend."""
import os
import sys
from pathlib import Path
from typing import Optional


def resolve_frontend_dist() -> Optional[str]:
    """Locate the built frontend (Vite dist) folder for static serving.

    Supports running from source as well as PyInstaller onefile bundles (using _MEIPASS).
    Returns an absolute path or None if no build is found.
    """
    candidates = []

    # PyInstaller onefile extracts into a temp dir pointed to by _MEIPASS
    if getattr(sys, "_MEIPASS", None):
        base = sys._MEIPASS  # type: ignore[attr-defined]
        candidates.append(os.path.join(base, "frontend", "dist"))
        candidates.append(os.path.join(base, "dist"))

    here = os.path.abspath(os.path.dirname(__file__))
    project_root = os.path.abspath(os.path.join(here, os.pardir, os.pardir))
    candidates.append(os.path.join(here, "frontend", "dist"))
    candidates.append(os.path.join(project_root, "frontend", "dist"))
    candidates.append(os.path.join(project_root, "dist"))

    for path in candidates:
        index_path = os.path.join(path, "index.html")
        if os.path.isfile(index_path):
            return os.path.abspath(path)
    return None
