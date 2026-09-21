# Platform scope

Windows remains the existing distribution. The initial Linux/macOS targets below
define the native packaging scope. Native installer lifecycle and Linux automatic
first-launch dependency setup checks passed in CI. Signed releases are not available yet.

| Target | Architecture | Image/video generation | Display management | Delivery |
| --- | --- | --- | --- | --- |
| Windows (existing target) | x64 | NVIDIA CUDA | Yes | Existing Windows installer |
| Ubuntu 24.04 LTS | x64 | NVIDIA CUDA | Yes | One .deb with automatic generation setup |
| macOS 15 or later | Apple Silicon / ARM64 | Disabled | Yes | Unsigned management .dmg |

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

## Native installation and generation setup

Linux ships one `.deb` containing Electron, the web app, standalone Python, USB
support, and the small base backend. Image/video generation is a core feature.
First launch automatically checks NVIDIA availability, downloads the pinned
CUDA/PyTorch and image/video dependencies, verifies them, and starts the server.
There is no optional ?enable generation? setting or management-only Linux download.

macOS currently ships a management `.dmg`; its MPS generation backend is not yet
implemented. Windows keeps its existing installer-time dependency setup.
See [installation instructions](NATIVE_INSTALL.md) and [USB setup](USB_SETUP.md).

## Runtime storage and reuse

`installer/build-native-runtime.py` bundles checksum-verified CPython 3.12.14
from `installer/native-python.json`. Linux also includes the setup helper,
project generation requirements, and pinned Linux CUDA constraints.

`installer/linux-generation-setup.py` creates a private runtime under Electron's
user-data directory, in `generation-runtime`. The runtime key includes Python,
base-package versions, and generation requirements/constraints, not app version.
App-only updates reuse the dependencies; changed dependency sets get a new
runtime. App imports point to the current installed server source.

Setup streams package download/install output and phase messages to the desktop
startup screen. Failed downloads offer retry. Closing the app stops the setup
process group; reopening retries an incomplete setup. Only verified runtimes
receive a ready marker. Cached downloads and completed runtimes survive updates
and uninstall. Models and creations stay in their existing separate locations.

An unavailable or incompatible NVIDIA GPU is clearly reported. Retry is offered;
users can still open display tools. Management remains a fallback, not a Linux
installation choice. Model weights download separately when selected.

## CI and artifacts

The Windows/Ubuntu/macOS matrix retains source tests, native storage checks,
base-runtime relocation checks, packaged desktop smoke checks, and installer
installation/replacement/repair/removal checks. The Linux installed-app smoke
check exercises the unsupported-GPU message and its display-tools fallback.

The separate **Linux dependency setup checks (x64)** job downloads the real
pinned dependencies through the same setup helper used by the desktop. It verifies
image/LTX/Wan imports, native torchvision, FFmpeg, app startup, and no-GPU behavior.
It also checks offline reuse across an app-version change. Only this CI helper
invocation bypasses the physical GPU precheck; the shipped desktop never does.
No model weights or image/video generation are run on hosted CPU-only runners.

Only `installer-linux-x64` and `installer-darwin-arm64` artifacts, with versioned
filenames and adjacent SHA-256 checksums, are uploaded. Intermediate backend and
desktop bundles remain build inputs and are no longer compressed/uploaded.
Signing/notarization, automatic app updates, and cross-version settings migration
remain separate work. The user confirmed that installer lifecycle and automatic
Linux generation-setup checks passed in CI; physical GPU computation is not covered.
