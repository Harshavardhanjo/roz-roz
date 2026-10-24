"""Vercel entry point: Vercel's Python runtime serves the ASGI app named `app` from this file.

Vercel loads this file on its own, so the project root (where the `app` package lives) isn't guaranteed to be on
sys.path; add it before importing."""

import sys
from pathlib import Path

ROOT = str(Path(__file__).resolve().parent.parent)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from app.main import app  # noqa: E402,F401
