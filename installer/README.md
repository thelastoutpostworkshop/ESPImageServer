# Windows installer maintenance

Use `build-installer.ps1` from the repository root when an installer build is
requested. The build machine needs Python 3.12 or newer, Node dependencies, and
Inno Setup 6. The script prefers the project's development interpreter; use
`-BuildPython <python.exe>` to select another build interpreter. Installed apps
never use this interpreter or search for a system Python installation.

The build script synchronizes versions from `pyproject.toml`, builds the frontend,
prepares a fresh standalone Python bundle, builds Electron, and passes both
fresh bundle paths to Inno. Direct Inno compilation requires
`/DRuntimeBuildOutput=<backend bundle>` and must not reuse an unrelated or stale
runtime. `RuntimeBuildOutput` is the directory containing `.venv`,
`runtime-manifest.json`, and `requirements-resolved.txt`.

`native-python.json` pins the full CPython distribution and SHA-256 digest from
python-build-standalone. Windows uses the x64 MSVC install-only archive, which
includes pip. Keep the entire prefix, including Python and dependency license
notices. Update the pinned version, release, URLs, and verified upstream hashes
when shipping Python security updates, then run the runtime checks for every
changed target. Never substitute a developer virtual environment or the minimal
Python embeddable ZIP.

Setup copies the base prefix into `runtime-base`, with its manifest and resolved
basic dependencies. Bootstrap creates a separate `runtime-staging-<GUID>` copy,
downloads the pinned generation packages, checks imports, bundled FFmpeg, and
CUDA, and activates it as `runtime` only after validation. A recovery journal
protects the previous runtime during activation. Settings, downloaded models,
and creations live outside these runtime directories. Setup runs per-user; the
separate Microsoft Visual C++ prerequisite can request administrator approval.

The application starts `runtime\python.exe` with isolated Python settings.
Relative `.pth` files locate the application's source after relocation. Always
invoke Python modules through the private interpreter, rather than using pip's
generated console launchers, whose embedded paths can refer to build staging.

Windows support starts at Windows 10 22H2 or Windows 11 22H2, matching the shipped
CUDA 12.8 requirements. An early Inno check rejects unsupported versions before
prerequisite downloads or app-file changes. See the
[CUDA support table](https://docs.nvidia.com/cuda/archive/12.8.0/cuda-installation-guide-microsoft-windows/index.html#system-requirements).

Focused Python and desktop tests exercise staging, activation recovery, command
isolation, and packaging without running a production installer. Platform CI
also builds and relocates the real basic runtime, starts its isolated server,
checks web assets and FFmpeg, and verifies failure behavior using harmless Inno
fixtures. These checks do not establish GPU generation or interactive Windows
installer acceptance. Use a freshly requested installer build in Sandbox for
those installation checks; test actual generation separately on supported
NVIDIA hardware. The [Sandbox test launcher and guide](../scripts/sandbox/README.md)
prepare isolated inputs, collect guest logs, and exercise cancellation and retry
without sharing the host installation or image library with the guest.
