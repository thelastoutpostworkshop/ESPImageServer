"""Prepare checksum-verified esptool for the native desktop build."""
import hashlib
import platform
from pathlib import Path
import shutil
import sys
import tarfile
import tempfile
import urllib.request

TARGETS = {
    ("linux", "x86_64"): ("linux-amd64", "49d572d50f6b1f089d1d81d3bd3bd357fbcc40f4f8fd4874f2dc51ad534abb01"),
    ("darwin", "arm64"): ("macos-arm64", "5d5aab5b64b10dc5001cfa96b5bfa48393ae561e6d797c41a1fdd3f5d3843d03"),
}


def prepare():
    target, digest = TARGETS[(sys.platform, platform.machine().lower())]
    tools = Path(__file__).resolve().parents[1] / "desktop/tools/esptool"
    tools.mkdir(parents=True, exist_ok=True)
    destination = tools / f"esptool-{target}"
    if destination.exists():
        raise ValueError(f"Output already exists: {destination}")
    with tempfile.TemporaryDirectory(dir=tools) as temporary:
        root = Path(temporary)
        archive = root / "esptool.tar.gz"
        url = f"https://github.com/espressif/esptool/releases/download/v5.1.0/esptool-v5.1.0-{target}.tar.gz"
        with urllib.request.urlopen(url, timeout=120) as response, archive.open("wb") as output:
            shutil.copyfileobj(response, output)
        with archive.open("rb") as source:
            if hashlib.file_digest(source, "sha256").hexdigest() != digest:
                raise ValueError("esptool archive checksum mismatch")
        with tarfile.open(archive) as package:
            package.extractall(root / "extracted", filter="data")
        extracted = root / "extracted" / f"esptool-{target}"
        if not (extracted / "esptool").is_file():
            raise ValueError("Unexpected esptool archive layout")
        (extracted / "esptool").chmod(0o755)
        extracted.rename(destination)
    print(f"Prepared esptool 5.1.0: {destination}")


if __name__ == "__main__":
    prepare()
