# Platform scope

Windows remains the existing distribution. The initial Linux/macOS targets below
define upcoming packaging work; Linux/macOS installers are not available yet.

| Target | Architecture | Image/video generation | Display management | Delivery |
| --- | --- | --- | --- | --- |
| Windows (existing target) | x64 | NVIDIA CUDA | Yes | Existing Windows installer |
| Ubuntu 24.04 LTS | x64 | NVIDIA CUDA | Yes | Planned |
| macOS 15 or later | Apple Silicon / ARM64 | Disabled | Yes | Planned |

Ubuntu 24.04 is the initial Linux distribution baseline. Other distributions,
older macOS versions, Intel Macs, Linux ARM64, and native Windows ARM64 packages
are outside this initial scope. CI uses macOS 15 as the minimum macOS target;
this does not claim coverage of every newer OS version.

Generation requires a working NVIDIA CUDA device and the selected model's
requirements. Without CUDA, the app retains display management, saved creations,
and SD-card tools. CPU and Apple Metal/MPS generation stay disabled. CPU offload
used by some CUDA models does not enable CPU-only generation.

## Automated coverage

`Platform checks` uses Windows 2025 x64, Ubuntu 24.04 x64, and macOS 15 ARM64.
The Windows runner is a CI host, not a change to the Windows installer OS policy.
The workflow checks Python and Node platform/architecture before running tests.
Runner labels follow the [GitHub runner reference](https://docs.github.com/en/actions/reference/runners/github-hosted-runners).

The matrix covers backend/frontend tests, native storage persistence, bundled
FFmpeg, and Electron lifecycle/preload checks. GPU pipelines and native USB work
are mocked; folder dialogs/openers are stubbed. A passing run establishes this
automated coverage, not availability of a packaged Linux/macOS release.

## Packaging implementation scope

The first backend bundle builder is implemented in
`installer/build-native-runtime.py`. CI builds management-only bundles for Linux
x64 and macOS ARM64 and uploads `backend-linux-x64` and `backend-darwin-arm64`
artifacts, retained for seven days. These are backend components, not installers.
The user confirmed that the hosted builds and relocation checks passed on both targets.

The Python runtime is pinned to CPython 3.12.14 from
[python-build-standalone](https://github.com/astral-sh/python-build-standalone/releases/tag/20260901),
with archive SHA-256 values recorded in `installer/native-python.json`. Its full
prefix occupies `.venv` for compatibility with the desktop runtime contract;
it is not a virtualenv linked to system Python. Management requirements reuse
the existing constraints without installing Torch or Diffusers. The bundle keeps
the standalone distribution's license files, package metadata, resolved package
versions, application license, and runtime manifest.

CI relocates the bundle into a path with spaces and Unicode and runs it with
isolated Python flags. The server child has an empty PATH. Checks cover Python
prefix/import locations, no GPU stack, bundled FFmpeg encode/decode, version,
management HTTP endpoints, generation rejection, and packaged frontend assets.
Linux CUDA dependencies remain separate.

## Native desktop bundles

`desktop/build-native.mjs` now builds Linux x64 and macOS ARM64 directory bundles
with the standalone backend, web assets, Electron, serialport bindings, and
checksum-verified esptool 5.1.0. The existing Windows build remains unchanged.
The application version comes from the backend manifest, derived from pyproject.toml.

CI relocates and launches the actual packaged executable using Playwright's
Electron driver. It checks `app.isPackaged`, backend import location, rendered
workspace, preload IPC, serial-port enumeration, esptool version, owned-server
shutdown, and port release. macOS also exercises window reopening. The backend
receives only a test isolation hook through PYTHONPATH, never checkout app source;
the test process PATH contains only Linux's `udevadm` when needed by serialport,
with no system Python or FFmpeg. No flashing or generation is performed.

After checks pass, CI uploads `desktop-linux-x64` and `desktop-darwin-arm64` tar
archives for seven days. Linux contains an `espimageserver` executable; macOS
contains `ESPImageServer.app`. These are unsigned management-only development
bundles, not final installers. Native build/smoke results are pending the first run.
Linux CUDA, signing/notarization, and installer/update formats remain unfinished.

- Preserve the current Windows installer and runtime layout.
- Prepare Linux x64 and macOS ARM64 Python 3.12 runtimes without requiring a
  system Python. Keep management dependencies separate from the Linux CUDA stack;
  the macOS package must not install CUDA or offer generation.
- Package matching Electron/serialport native binaries, the imageio-ffmpeg
  executable, and esptool for each target. Do not require system FFmpeg or Arduino.
- Implement the existing non-Windows runtime layout contract in
  `desktop/runtime.mjs`: backend under `resources/backend`, Python under
  `.venv/bin/python`, and esptool under the platform-specific resources tool path.
  Produce these runtimes on native CI runners; do not copy a Windows virtualenv.
- Native bundle commands and packaged startup checks are implemented above.
  Signing and update flows remain separate work.
