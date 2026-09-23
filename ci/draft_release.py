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
        "installer-darwin-arm64": f"ESPImageServer-{version}-darwin-arm64.dmg",
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


def ensure_unused_version(repo: str, tag: str) -> None:
    pages = json.loads(subprocess.check_output(
        ["gh", "api", f"repos/{repo}/releases", "--paginate", "--slurp"], text=True))
    if any(release["tag_name"] == tag for page in pages for release in page):
        raise ValueError(f"Release {tag} already exists. Review it or choose a new version; no assets were changed.")
    result = subprocess.run(["git", "ls-remote", "--exit-code", "--tags", "origin", f"refs/tags/{tag}"],
                            capture_output=True, text=True)
    if result.returncode == 0:
        raise ValueError(f"Tag {tag} already exists. Choose an unused version.")
    if result.returncode != 2:
        raise RuntimeError(f"Could not check existing tags: {result.stderr}")


def main() -> None:
    if os.environ.get("GITHUB_ACTIONS") != "true" or os.environ.get("GITHUB_EVENT_NAME") != "workflow_dispatch":
        raise RuntimeError("Run through the manually dispatched Prepare draft release workflow")
    version = project_version(Path("pyproject.toml"))
    assets = validate_assets(Path(sys.argv[1]), version)
    repo, sha = os.environ["GITHUB_REPOSITORY"], os.environ["GITHUB_SHA"]
    if not re.fullmatch(r"[0-9a-f]{40}", sha):
        raise ValueError("Expected the full tested commit SHA")
    tag = f"v{version}"
    ensure_unused_version(repo, tag)
    notes = f"""Draft for review — ESPImageServer {version}

Built from `{sha}` after automated platform, installer lifecycle, and Linux dependency setup checks.

| Download | Platform | Generation |
| --- | --- | --- |
| `.exe` | Windows x64 | Image and video generation with a supported NVIDIA GPU; setup downloads dependencies |
| `.deb` | Ubuntu 24.04 x64 | Image and video generation with a supported NVIDIA GPU; first launch downloads dependencies |
| `.dmg` | macOS 15+ Apple Silicon | Display management only; generation is not available yet |

Installers are unsigned; the macOS app is not notarized. SHA-256 files accompany each installer.
The automated checks do not run generation on a physical GPU. Windows upgrade checks use fixture payloads.

Before publishing, add the user-facing changes for this version and review the attached downloads.
"""
    with tempfile.TemporaryDirectory() as temporary:
        body = Path(temporary) / "release-notes.md"
        body.write_text(notes, encoding="utf-8")
        subprocess.run(["gh", "release", "create", tag, *map(str, assets), "--repo", repo,
                        "--draft", "--target", sha, "--title", f"ESPImageServer {version}",
                        "--notes-file", str(body)], check=True)
    with Path(os.environ["GITHUB_STEP_SUMMARY"]).open("a", encoding="utf-8") as stream:
        stream.write(f"Created **{tag}** as an unpublished draft with three installers and three checksums.\n"
                     f"Review it under [Releases](https://github.com/{repo}/releases). Nothing was published.\n")


if __name__ == "__main__":
    main()
