"""Application version sourced from the repository's pyproject.toml."""

from __future__ import annotations

from pathlib import Path
import re


def _read_version() -> str:
    project_file = Path(__file__).resolve().parents[2] / "pyproject.toml"
    try:
        match = re.search(r'^version\s*=\s*"([^"]+)"', project_file.read_text(encoding="utf-8"), re.MULTILINE)
    except OSError:
        match = None
    return match.group(1) if match else "unknown"


APP_VERSION = _read_version()
