"""Exercise native install/replacement/repair/removal on disposable hosted runners."""
import argparse
import hashlib
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

PROJECT = Path(__file__).resolve().parents[1]


def run(*args, **kwargs):
    return subprocess.run(args, check=True, **kwargs)


def smoke(root, mode):
    command = ["node", str(PROJECT / "desktop/packaged-smoke.mjs"), str(root), mode]
    if sys.platform == "linux":
        command = ["xvfb-run", "--auto-servernum", *command]
    run(*command)


def main(directory, mode):
    if not os.environ.get("CI") or sys.platform not in ("linux", "darwin"):
        raise RuntimeError("Run only on disposable native CI runners")
    extension = ".deb" if sys.platform == "linux" else ".dmg"
    packages = list(directory.resolve().glob("*" + extension))
    if len(packages) != 1:
        raise RuntimeError("Expected one installer")
    package = packages[0]
    with package.open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    assert package.with_name(package.name + ".sha256").read_text().strip() == f"{digest}  {package.name}"
    with tempfile.TemporaryDirectory(prefix="esp-install-") as temporary:
        root = Path(temporary)
        # Keep representative external user data alongside the installation.
        # These must survive replacement, repair, and removal byte-for-byte.
        fixtures = {}
        for name in ("config/settings.json", "data/image_library_index.json", "cache/models/weights", "creations/art.jpg", "creations/videos/clip.mp4"):
            file = root / "user" / name
            file.parent.mkdir(parents=True, exist_ok=True)
            file.write_bytes(b"preserve existing user content")
            fixtures[file] = file.read_bytes()

        def preserved():
            for file, content in fixtures.items():
                assert file.read_bytes() == content, f"User data changed: {file}"

        if sys.platform == "linux":
            existing = subprocess.run(["dpkg-query", "-W", "-f=${Status}", "espimageserver"], capture_output=True, text=True)
            if "install ok installed" in existing.stdout:
                raise RuntimeError("Refusing to replace a pre-existing installation")
            assert subprocess.check_output(["dpkg-deb", "-f", str(package), "Package"], text=True).strip() == "espimageserver"
            assert subprocess.check_output(["dpkg-deb", "-f", str(package), "Architecture"], text=True).strip() == "amd64"
            installed = Path("/opt/ESPImageServer")
            if installed.exists():
                raise RuntimeError("Refusing to replace an existing application directory")
            try:
                run("sudo", "apt-get", "install", "-y", "--no-install-recommends", str(package))
                assert Path("/usr/bin/espimageserver").resolve() == installed / "espimageserver"
                smoke(installed, mode)
                preserved()
                # Same-version replacement tests package-manager overwrite behavior.
                run("sudo", "apt-get", "install", "-y", "--reinstall", str(package))
                preserved()
                # Remove a known application file, then repair it from the package.
                run("sudo", "rm", "--", str(installed / "espimageserver"))
                run("sudo", "apt-get", "install", "-y", "--reinstall", str(package))
                smoke(installed, mode)
                preserved()
            finally:
                run("sudo", "apt-get", "remove", "-y", "espimageserver")
            assert not (installed / "espimageserver").exists()
            assert not Path("/usr/bin/espimageserver").exists()
            preserved()
        else:
            mount = root / "volume"
            run("hdiutil", "verify", str(package))
            run("hdiutil", "attach", "-readonly", "-nobrowse", "-mountpoint", str(mount), str(package))
            try:
                assert (mount / "Applications").is_symlink()
                applications = root / "Applications"
                applications.mkdir()
                destination = applications / "ESPImageServer.app"

                def replace():
                    staging = applications / "new.app"
                    run("ditto", str(mount / "ESPImageServer.app"), str(staging))
                    if destination.exists():
                        backup = applications / "previous.app"
                        destination.rename(backup)
                        staging.rename(destination)
                        shutil.rmtree(backup)
                    else:
                        staging.rename(destination)

                replace()
                smoke(applications, mode)
                preserved()
                replace()
                preserved()
                (destination / "Contents/MacOS/ESPImageServer").unlink()
                replace()
                smoke(applications, mode)
                preserved()
                shutil.rmtree(destination)
                preserved()
            finally:
                run("hdiutil", "detach", str(mount))
    print("Native installer checksum, installation, replacement, repair, and removal checks passed")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    parser.add_argument("mode", choices=("management", "cuda"))
    args = parser.parse_args()
    main(args.directory, args.mode)
