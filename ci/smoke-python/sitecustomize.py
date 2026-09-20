"""Isolate only smoke-test Python children before the application is imported."""

import os
from pathlib import Path

if directory := os.getenv("ESP_DESKTOP_SMOKE_STORAGE"):
    root = Path(directory)
    Path.home = classmethod(lambda cls: root / "home")
    # Record the actual interpreter PID (the Windows venv launcher may differ).
    (root / f"python-{os.getpid()}.pid").write_text(str(os.getpid()))
