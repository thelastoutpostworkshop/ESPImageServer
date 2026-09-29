"""Validate this run's installers and create a draft only; never publish/replace."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import tomllib


def project_version(project: Path) -> str:
    version = tomllib.loads(project.read_text(encoding="utf-8"))["project"]["version"]
    if not re.fullmatch(r"\d+\.\d+\.\d+", version):
        raise ValueError("Release version must use major.minor.patch in pyproject.toml")
    return version


def validate_assets(root: Path, version: str) -> list[Path]:
    expected = {
        "installer-win32-x64": f"ESPImageServer-Setup-{version}.exe",
        "installer-linux-x64": f"ESPImageServer-{version}-linux-x64.deb",
    }
    wanted = {f"{folder}/{name}{suffix}" for folder, name in expected.items()
              for suffix in ("", ".sha256")}
    actual = {p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file()}
    if actual != wanted or any(p.is_symlink() for p in root.rglob("*")):
        raise ValueError(f"Installer set differs from version {version}: missing={wanted - actual}, unexpected={actual - wanted}")
    assets = []
    for folder, name in expected.items():
        installer = root / folder / name
        checksum = installer.with_name(name + ".sha256")
        if installer.stat().st_size == 0:
            raise ValueError(f"Empty installer: {name}")
        with installer.open("rb") as stream:
            digest = hashlib.file_digest(stream, "sha256").hexdigest()
        if checksum.read_text(encoding="utf-8").strip() != f"{digest}  {name}":
            raise ValueError(f"Checksum mismatch: {name}")
        assets.extend((installer, checksum))
    return assets


def release_tag(version: str) -> str:
    if (os.environ.get("GITHUB_ACTIONS") != "true"
            or os.environ.get("GITHUB_EVENT_NAME") != "push"
            or os.environ.get("GITHUB_REF_TYPE") != "tag"):
        raise RuntimeError("Release workflow requires a pushed version tag")
    tag = os.environ.get("GITHUB_REF_NAME", "")
    if tag != f"v{version}":
        raise ValueError(f"Tag must be v{version} to match pyproject.toml; got {tag!r}")
    return tag


def ensure_unused_version(repo: str, tag: str, sha: str) -> None:
    pages = json.loads(subprocess.check_output(
        ["gh", "api", f"repos/{repo}/releases", "--paginate", "--slurp"], text=True))
    if any(release["tag_name"] == tag for page in pages for release in page):
        raise ValueError(f"Release {tag} already exists. Review it or choose a new version; no assets were changed.")
    result = subprocess.run(["git", "ls-remote", "--exit-code", "--tags", "origin", f"refs/tags/{tag}", f"refs/tags/{tag}^{{}}"],
                            capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"Could not check existing tags: {result.stderr}")
    refs = dict(line.split()[::-1] for line in result.stdout.splitlines())
    remote_sha = refs.get(f"refs/tags/{tag}^{{}}", refs.get(f"refs/tags/{tag}"))
    if remote_sha != sha:
        raise ValueError(f"Tag {tag} no longer points to the tested commit")


def main() -> None:
    version = project_version(Path("pyproject.toml"))
    tag = release_tag(version)
    if sys.argv[1:] == ["--check-tag"]:
        print(f"Release tag {tag} matches pyproject.toml")
        return
    assets = validate_assets(Path(sys.argv[1]), version)
    repo, sha = os.environ["GITHUB_REPOSITORY"], os.environ["GITHUB_SHA"]
    if not re.fullmatch(r"[0-9a-f]{40}", sha):
        raise ValueError("Expected the full tested commit SHA")
    ensure_unused_version(repo, tag, sha)
    download_base = f"https://github.com/{repo}/releases/download/{tag}"
    notes = f"""Draft for review — ESPImageServer {version}

Built from `{sha}` after automated platform, installer lifecycle, and Linux dependency setup checks.

| Download | Platform | Generation |
| --- | --- | --- |
| [Download Windows installer (.exe)]({download_base}/ESPImageServer-Setup-{version}.exe) | Windows x64 | Image and video generation with a supported NVIDIA GPU; setup downloads dependencies |
| [Download Linux installer (.deb)]({download_base}/ESPImageServer-{version}-linux-x64.deb) | Ubuntu 24.04 x64 | Image and video generation with a supported NVIDIA GPU; first launch downloads dependencies |

Installers are unsigned. SHA-256 files accompany each installer. macOS is deferred from this release.

## Windows installation

Quit ESPImageServer, run `ESPImageServer-Setup-{version}.exe`, and follow setup. You can install over an existing version. Setup downloads the generation dependencies; internet access and sufficient free disk space are required.

1. Choose NVIDIA CUDA acceleration for generation, or display management only for setup, saved creations, and SD-card tools.
2. Choose an initial image model. Its files download during setup or the first time you select it.
3. Open **ESPImageServer** from the Start Menu or desktop shortcut.

Setup uses CPython 3.12. If it is not already installed, the installer asks Windows Package Manager to install it; other Python versions already on the computer are left alone.

## Ubuntu 24.04 installation

Quit ESPImageServer and any separately started server. From the download directory, run:

```sh
sudo apt install './ESPImageServer-{version}-linux-x64.deb'
```

Launch **ESPImageServer** from the applications menu or run `espimageserver` as your normal user, without sudo. First launch checks your NVIDIA GPU and downloads several GB of generation dependencies. Install a compatible NVIDIA driver beforehand; the app does not install drivers. Model weights download separately when selected.

The startup screen shows download progress. If setup fails, choose **Retry setup**; closing and reopening the app also retries incomplete setup. Without a compatible GPU, you can retry the GPU check or open display tools.

To update, quit the app and install the newer `.deb` with the same command. App-only updates reuse verified generation dependencies. To repair this version:

```sh
sudo apt install --reinstall './ESPImageServer-{version}-linux-x64.deb'
```

To uninstall:

```sh
sudo apt remove espimageserver
```

## Open the app in a browser

The desktop app starts the local server automatically. While it is running, you can also open the app at `http://127.0.0.1:8000` in a browser.

## Your saved data

Updating or uninstalling keeps settings, downloaded models, and saved creations stored outside the installation folder. Linux also retains its generation runtime and cached setup downloads. Keep personal files outside the installation directory.

## Automated checks

The automated checks do not run generation on a physical GPU. Windows upgrade checks use fixture payloads.

Before publishing, add the user-facing changes for this version and review the attached downloads.
"""
    with tempfile.TemporaryDirectory() as temporary:
        body = Path(temporary) / "release-notes.md"
        body.write_text(notes, encoding="utf-8")
        subprocess.run(["gh", "release", "create", tag, *map(str, assets), "--repo", repo,
                        "--draft", "--verify-tag", "--target", sha, "--title", f"ESPImageServer {version}",
                        "--notes-file", str(body)], check=True)
    with Path(os.environ["GITHUB_STEP_SUMMARY"]).open("a", encoding="utf-8") as stream:
        stream.write(f"Created **{tag}** as an unpublished draft with two installers and two checksums.\n"
                     f"Review it under [Releases](https://github.com/{repo}/releases). Nothing was published.\n")


if __name__ == "__main__":
    main()
