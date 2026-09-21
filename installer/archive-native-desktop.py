"""Create versioned native desktop archives and verify their contents before upload."""
import argparse
import hashlib
import json
from pathlib import Path
import tarfile
import tomllib

PROJECT = Path(__file__).resolve().parents[1]


def digest(stream):
    return hashlib.file_digest(stream, "sha256").hexdigest()


def verify(archive, source):
    """Read every archived file back, including permissions and symbolic links."""
    expected = {"."} | {"./" + p.relative_to(source).as_posix() for p in source.rglob("*")}
    seen = set()
    with tarfile.open(archive, "r:gz") as packed:
        for entry in packed:
            if entry.name not in expected or entry.name in seen:
                raise ValueError(f"Unexpected archive entry: {entry.name}")
            seen.add(entry.name)
            original = source / entry.name
            if entry.mode != original.lstat().st_mode & 0o7777:
                raise ValueError(f"Permission mismatch: {entry.name}")
            if original.is_symlink():
                if not entry.issym() or entry.linkname != original.readlink().as_posix():
                    raise ValueError(f"Link mismatch: {entry.name}")
            elif original.is_dir():
                if not entry.isdir():
                    raise ValueError(f"Directory mismatch: {entry.name}")
            else:
                if not entry.isfile():
                    raise ValueError(f"File type mismatch: {entry.name}")
                with original.open("rb") as actual, packed.extractfile(entry) as archived:
                    if digest(actual) != digest(archived):
                        raise ValueError(f"Content mismatch: {entry.name}")
    if seen != expected:
        raise ValueError("Archive is missing files")


def build(source, output, target, mode, version):
    source, output = source.resolve(), output.resolve()
    if target not in ("linux-x64", "darwin-arm64"):
        raise ValueError("Unsupported native target")
    if mode not in ("management", "cuda") or (mode == "cuda" and target != "linux-x64"):
        raise ValueError("Unsupported native mode")
    if output.is_relative_to(source):
        raise ValueError("Archive output must be outside the bundle")
    resources = source / ("resources" if target == "linux-x64" else "ESPImageServer.app/Contents/Resources")
    manifest = json.loads((resources / "backend/runtime-manifest.json").read_text(encoding="utf-8"))
    if any(manifest.get(key) != value for key, value in
           (("target", target), ("mode", mode), ("app_version", version))):
        raise ValueError("Bundle manifest differs from requested target, mode, or project version")
    # Version is also a filename component; never accept path separators.
    if not version or any(c not in "0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ.-+" for c in version):
        raise ValueError("Invalid version")
    output.mkdir(parents=True, exist_ok=True)
    archive = output / f"ESPImageServer-{version}-{target}-{mode}.tar.gz"
    checksum = archive.with_name(archive.name + ".sha256")
    if archive.exists() or checksum.exists():
        raise ValueError("Distribution output already exists")
    temporary = archive.with_suffix(".partial")
    try:
        with tarfile.open(temporary, "x:gz", compresslevel=1, dereference=False) as packed:
            # Disable hard-link deduplication so verification reads each file directly.
            def metadata(entry):
                packed.inodes.clear()
                entry.uid = entry.gid = 0
                entry.uname = entry.gname = ""
                return entry
            packed.add(source, arcname=".", filter=metadata)
        verify(temporary, source)
        with temporary.open("rb") as stream:
            sha256 = digest(stream)
        temporary.rename(archive)
        checksum.write_text(f"{sha256}  {archive.name}\n", encoding="ascii")
    finally:
        temporary.unlink(missing_ok=True)
    return archive


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("target", choices=("linux-x64", "darwin-arm64"))
    parser.add_argument("mode", choices=("management", "cuda"))
    args = parser.parse_args()
    version = tomllib.loads((PROJECT / "pyproject.toml").read_text(encoding="utf-8"))["project"]["version"]
    print(build(args.source, args.output, args.target, args.mode, version))
