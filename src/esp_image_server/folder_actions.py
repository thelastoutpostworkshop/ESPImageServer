"""Native actions on the server computer, separate from library storage."""

import os
from pathlib import Path
import shutil
import subprocess
import sys


class FolderActionUnavailable(RuntimeError):
    pass


def capabilities() -> dict[str, bool]:
    windows = sys.platform == "win32"
    desktop_linux = sys.platform.startswith("linux") and bool(os.getenv("DISPLAY") or os.getenv("WAYLAND_DISPLAY"))
    return {
        "choose": windows and shutil.which("powershell") is not None,
        "reveal": windows or (sys.platform == "darwin" and Path("/usr/bin/open").is_file())
        or (desktop_linux and shutil.which("xdg-open") is not None),
    }


def reveal_folder(folder: Path) -> None:
    if not capabilities()["reveal"]:
        raise FolderActionUnavailable("Opening folders is unavailable on this server. Use the library path in your file manager.")
    folder.mkdir(parents=True, exist_ok=True)
    if sys.platform == "win32":
        os.startfile(folder)
    else:
        command = "/usr/bin/open" if sys.platform == "darwin" else shutil.which("xdg-open")
        subprocess.run([command, str(folder)], check=True, capture_output=True, timeout=15)


def choose_folder(current: Path) -> str:
    if not capabilities()["choose"]:
        raise FolderActionUnavailable("A folder chooser is unavailable on this server. Use the ESPImageServer desktop app to choose a library folder.")
    command = (
        "[Console]::OutputEncoding=[System.Text.UTF8Encoding]::new($false); "
        "Add-Type -AssemblyName System.Windows.Forms; "
        "$dialog = New-Object System.Windows.Forms.FolderBrowserDialog; "
        "$dialog.Description = 'Choose an empty folder for ESPImageServer images'; "
        "$dialog.SelectedPath = '" + str(current).replace("'", "''") + "'; "
        "if ($dialog.ShowDialog() -eq [System.Windows.Forms.DialogResult]::OK) { "
        "[Console]::Out.Write($dialog.SelectedPath) }"
    )
    result = subprocess.run(["powershell", "-NoProfile", "-STA", "-Command", command],
                            capture_output=True, text=True, encoding="utf-8", check=True)
    return result.stdout.strip()
