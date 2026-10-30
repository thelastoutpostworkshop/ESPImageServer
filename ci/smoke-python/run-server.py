"""Explicit development smoke entry; never included in application packages."""

from pathlib import Path
import runpy
import sys


here = Path(__file__).resolve().parent
# The CI development venv contains API dependencies, not an installed app.
sys.path.insert(0, str(here.parents[1] / "src"))
runpy.run_path(str(here / "sitecustomize.py"), run_name="_esp_smoke_isolation")
runpy.run_module("esp_image_server", run_name="__main__", alter_sys=True)
