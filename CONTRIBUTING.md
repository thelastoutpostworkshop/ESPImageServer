# Contributing to ESPImageServer

Thanks for helping improve ESPImageServer. This project creates locally generated images for ESP32 displays. Keep changes practical, reliable, and friendly for makers.

## Project layout

- `src/esp_image_server/` — FastAPI server and image-generation logic.
- `frontend/` — Vue 3, Vite, and Vuetify web application.
- `desktop/` — Electron desktop shell for the local server and native folder actions.
- `installer/` — Windows installer sources.
- `tests/` — backend API and image-processing tests.

The ESP32 firmware lives in the separate `ESPImageDisplay` repository. Do not change it for server-only work, but consider it whenever changing an API or the JPEG format.

## Writable backend locations

Use `src/esp_image_server/paths.py` for default writable paths. Resolution does
not create directories or migrate files; stores create their directories when
writing. User-selected image libraries and explicit store paths remain unchanged.

| Purpose | Windows (unchanged) | Linux | macOS |
| --- | --- | --- | --- |
| Settings | `%LOCALAPPDATA%/ESPImageServer` | `$XDG_CONFIG_HOME/ESPImageServer` | `~/Library/Application Support/ESPImageServer` |
| Registry, library index, default images | `%LOCALAPPDATA%/ESPImageServer` | `$XDG_DATA_HOME/ESPImageServer` | `~/Library/Application Support/ESPImageServer` |
| Generated video results, converted media, SD thumbnails | `%LOCALAPPDATA%/ESPImageServer` | `$XDG_CACHE_HOME/ESPImageServer` | `~/Library/Caches/ESPImageServer` |
| Model downloads | `~/.cache/ESPImageServer/models` | `$XDG_CACHE_HOME/ESPImageServer/models` | `~/Library/Caches/ESPImageServer/models` |

Linux XDG defaults are `~/.config`, `~/.local/share`, and `~/.cache` respectively;
empty or relative XDG overrides are ignored. Windows retains its historical
`~/.local/ESPImageServer` fallback when LOCALAPPDATA is unset. Saved videos stay
in the image library's `videos` subfolder, separate from disposable video results.

`ESP_IMAGE_MODEL_CACHE` overrides the model-download location on every OS.
An explicitly supplied image-generation `Settings.model_cache_dir` takes
precedence over that environment variable. Image-model discovery also retains
the shared Hugging Face cache lookup and its existing environment overrides.

These paths prepare the backend for Linux/macOS; desktop packaging and hardware
support remain separate work. Existing experimental non-Windows storage under
`~/.local/ESPImageServer` is not automatically migrated. Electron continues to
use its own `app.getPath('userData')` for desktop state and firmware downloads.

## Desktop runtime boundary

`desktop/runtime.mjs` resolves Python, esptool, and icons without importing
Electron. Development uses the repository's `.venv/Scripts/python.exe` on
Windows and `.venv/bin/python` on Linux/macOS. There is no system-Python fallback.
Windows installed paths remain unchanged. Future non-Windows packages must
provide `resources/backend/.venv/bin/python` and a backend installed into that
environment; that bundle is not produced yet.

Tool locations are `tools/esptool/esptool-<target>/esptool` beneath the desktop
directory in development or Electron resources in a package. Windows uses
`windows-amd64/esptool.exe`; the other target directory conventions are
`linux-amd64`, `linux-aarch64`, `macos-amd64`, and `macos-arm64`. These conventions
do not imply binaries are bundled. Automatic download/verification still runs
only on Windows; the Node preparation entry point skips PowerShell elsewhere.
Missing tools produce an error before flashing starts and do not block management.

The desktop stops only Python processes it launched, using Windows process-tree
termination or POSIX termination with a bounded force-kill fallback. Connecting
to an existing server leaves its lifecycle with its owner. macOS keeps the app
and owned server running after the last window closes and recreates the window
on Dock activation; explicit Quit stops the owned server. Windows/Linux quit
when the last window closes. Native lifecycle verification remains in TODO.md.

## USB port handling

`desktop/serial-ports.mjs` owns serial-device enumeration and path validation.
Use exact enumerated paths, including Windows `COM26`, Linux `/dev/ttyUSB0` or
`/dev/ttyACM0`, and macOS `/dev/cu.usbmodem1101`. Do not normalize paths or assume
that a port name identifies a particular board. Selection requires a detected
port; USB operations re-enumerate before opening, then retain the existing
firmware hardware-ID checks. Low-level serial transports validate path syntax;
their callers are responsible for checking current enumeration.

The shared enumerator preserves serial number/vendor/product metadata for
reconnection checks. Native permissions, drivers, and esptool packaging still
require platform-specific validation. Automated serial tests use simulated
devices and do not flash boards or change Wi-Fi credentials.

## Native library folder actions

`folder_actions.py` isolates server-side folder actions. `/app-settings` reports
`folder_actions.choose` and `folder_actions.reveal`; unsupported endpoints return
501 with a path-entry explanation. Windows retains its PowerShell folder chooser
and Explorer action. macOS opening uses `/usr/bin/open`; Linux requires a desktop
session (`DISPLAY` or `WAYLAND_DISPLAY`) and `xdg-open`. Availability is a capability
hint: a native action can still fail at runtime, and errors are surfaced to the user.

Electron continues to prefer its own folder dialog and `shell.openPath` through
preload IPC. Browsers can enter an absolute library path in Settings, including on
headless servers. Paths refer to the server computer, and saving uses the existing
library relocation validation. Opening the folder uses the saved library location,
not an unsaved edit. Native chooser cancellation leaves settings unchanged.

## Generation capability policy

`generation_capabilities.py` owns device detection and model-family execution
rules independently of the host OS. CUDA availability is verified with an
allocation and synchronization before model downloads. Missing or unusable CUDA
leaves management available; `cpu` remains the API's management-only device marker.
CPU and MPS generation are not enabled.

The policy preserves image float16, LTX bfloat16 (including its text encoder),
and Wan bfloat16 with a float32 VAE and model CPU offload. Offload manages GPU
memory; it does not enable CPU generation. Pipeline placement, seeded random
generators, and CUDA cache cleanup use the shared policy. Model catalogs still
own IDs, step limits, and supported input types. API admission checks use the
requested model family; loaders recheck actual device availability before loading.

Keep the shared single-worker queue and image/video unload handoff intact when
adding a backend. Add explicit family policies and validate precision, offload,
cancellation, and actual GPU output before enabling another accelerator. Unit
tests mock model downloads/pipelines; they do not establish MPS or native-platform
generation support.

## Development setup

Use Python 3.12 and Node.js 22 (22.12 or newer).

Create a local Python environment and install the project with development dependencies:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
```

Install the frontend and desktop dependencies:

```powershell
npm --prefix frontend install
npm --prefix desktop install
```

Start the server during frontend development:

```powershell
.\.venv\Scripts\python.exe -m uvicorn esp_image_server.app:app --reload
```

The application is available at `http://127.0.0.1:8000`.

## Create a local firmware package and manifest

Use [scripts/package-firmware.ps1](scripts/package-firmware.ps1) to generate
`manifest.json` for a manually compiled ESPImageDisplay build. It requires
PowerShell 5.1 or newer. It does not compile firmware, flash a board, download
firmware, or build the installer.

### Prepare the version folder

Compile the intended firmware target with its matching Arduino profile in the
ESPImageDisplay repository. Use a fresh build without personal Wi-Fi credentials.
Copy the four binaries referenced by the build's `flash_args`, plus `flash_args`
and `build.options.json`, into a separate folder for that board and version.
Keep the filenames unchanged and do not mix files from different builds.

For example, the JC4827W543 package should look like this after generation:

```text
ESPImage Firmwares/
  JC4827W543/
    1.1.2/
      ESPImageDisplay.ino.bin
      ESPImageDisplay.ino.bootloader.bin
      ESPImageDisplay.ino.partitions.bin
      boot_app0.bin
      flash_args
      build.options.json
      manifest.json
```

Copy the individual binaries named in `flash_args`; the `.merged.bin` and
`_flashed.bin` files are not needed for this workflow. Keep firmware packages
outside the application repository so binaries do not increase its size.

### Generate or regenerate the manifest

From the ESPImageServer repository, run:

```powershell
& .\scripts\package-firmware.ps1 `
  -PackageDirectory 'C:\Users\charles\Desktop\ESPImage Firmwares\JC4827W543\1.1.2' `
  -BoardTarget JC4827W543 `
  -FirmwareVersion 1.1.2
```

Replace the example path with your own package folder. To run from another
directory, replace `.\scripts\package-firmware.ps1` with the full path to the
script in your checkout. Quote paths containing spaces.

| Parameter | Value to supply |
| --- | --- |
| `-PackageDirectory` | The version folder containing the six exported files, not the parent board folder. |
| `-BoardTarget` | `JC4827W543`, `ST7701_320X820`, `ESP32_C6_LCD_147`, or `CHEAP_YELLOW_DISPLAY`. |
| `-FirmwareVersion` | The version actually compiled, such as `1.1.2`. Changing this value does not change the binary. |

The script validates the package, reads the flash settings and offsets from
`flash_args`, reads chip/build configuration from `build.options.json`, and
calculates a SHA-256 checksum for each binary. It creates or replaces
`manifest.json` beside those files; the binaries remain unchanged. Regenerate
the manifest whenever you replace a binary. Use a new version folder for each
firmware release so older packages remain intact.

The manifest records schema version, package type, board, firmware version,
chip, build configuration, flash settings, and each binary's role, filename,
offset, size, and checksum. Board/version are publisher declarations; the script
cannot prove that the binary implements the selected display target or contains
no credentials. Checksums detect file changes, not publisher authenticity.

Supply optional `-ReleaseNotes 'Describe the changes for the display owner.'`
when generating a package. It writes plain-text `release_notes` (up to 2000
characters), shown with an available update. Do not put HTML or credentials in
release notes. Existing manifests without this field continue to work.
The desktop firmware library scans its selected root plus two folder levels,
validates complete packages, and recommends stable releases for the exact board.
Prereleases remain available through manual package selection.

After generation, open **Set up display** in the ESPImageServer desktop app
and check the firmware library, or select the version folder manually. The app validates the package again before
flashing. Firmware 1.1.2 supports USB identification so the running board/version
can be checked after installation. A normal browser tab cannot use the desktop
USB interface.

See [local firmware package details](scripts/firmware-packages.md) for validation
rules and supported layouts, and [USB identification](scripts/usb-identification.md)
for the protocol and manual hardware checks. Test the packaging script without
hardware using:

```powershell
& .\scripts\test-package-firmware.ps1
```

## Automated platform checks

`.github/workflows/platform-checks.yml` runs on pushes, pull requests, and manual
dispatch. It uses Windows 2025, Ubuntu 24.04, and macOS 15 hosted runners with
Python 3.12 and Node.js 22. See the [GitHub runner reference](https://docs.github.com/en/actions/reference/runners/github-hosted-runners)
for runner architectures and availability. This matrix is a code-portability
check, not a commitment to a release support matrix.

Each runner installs JavaScript dependencies with `npm ci`, runs frontend tests
and its production build, runs backend tests, and runs Electron module tests.
It also downloads Electron and launches the real desktop entry point against
the real Python server using a `.venv` with the CI backend dependencies.
The smoke test checks Vue rendering, preload IPC, owned-server shutdown and port
release, and preservation of an independently started server. On macOS it closes
the window and emits Electron's activation event to verify reopening before
quitting. This does not exercise a physical Dock click. Linux uses Xvfb; only the
CI smoke launcher disables Chromium's sandbox. No installer or esptool is built.

To run locally, build the frontend, prepare the normal project `.venv`, close
the app/server, then run `npm --prefix desktop run test:smoke` (use `xvfb-run
--auto-servernum` on headless Linux). The test refuses to run if port 8000 is
occupied. It opens temporary desktop windows but does not generate media or
send USB/display commands. Python home/data/cache paths and Electron user data
are isolated under a temporary directory, whose location is printed for
diagnostics. The test-only Python startup hook is supplied through `PYTHONPATH`;
it is not installed into the app or included in desktop packages.

`ci/requirements.txt` is a lightweight test environment, not an application
installation. It reuses common installer constraints, omits Torch/Diffusers and
model downloads, and runs the source through `PYTHONPATH=src`. GPU pipeline tests
use mocks; an additional management-only startup test uses the real device
detection with Torch unavailable. A tiny MP4 test exercises bundled FFmpeg.

The separate native-storage step runs `tests/test_native_storage.py`. Two fresh
Python processes start and stop the real FastAPI lifespan through TestClient,
save settings and a tiny fixture image, and check persistence using the host's
actual path rules. No HTTP listener, generation, or model download is required.
Linux also tests custom XDG directories. The copied source installation is made
read-only on Linux/macOS, with an explicit failed-write probe; Windows does not
claim POSIX permission coverage. All platforms check that installation files
stay unchanged and guard Python writes outside isolated user storage. Cache
location checks include a small model-cache marker, not real model loading.
Run this check as a normal user; privileged POSIX execution fails the read-only
probe rather than silently skipping it.

`tests/conftest.py` redirects writable user paths before test collection imports
the global FastAPI app. Tests must not read or write the developer's library or
model cache. Native dialogs, real GPU output/cancellation, physical USB behavior,
and packaged-app startup still require separate acceptance checks. Do not mark
Linux/macOS validation complete until the corresponding hosted jobs pass.

## Before submitting changes

Run the checks that apply to your change:

```powershell
.\.venv\Scripts\python.exe -m pytest
npm --prefix frontend run build
```

For Electron changes, also run:

```powershell
npm --prefix desktop run build
```

Do not commit virtual environments, generated installer files, logs, model caches, or `secrets.h`.

## ESP32 image contract

This is important when working on image output or display settings:

- Boards register their native display width and height with `POST /display`.
- Boards poll `GET /latest.jpg` and use the ETag to skip unchanged images.
- `/latest.jpg` must be a baseline JPEG at the display's exact native dimensions.
- Rotation is performed by the server through `/display-settings`, using `0`, `90`, `180`, or `270` degrees.
- Do not add equivalent image rotation to firmware unless the protocol is deliberately redesigned.

## UI and API guidelines

- Keep maker-facing text plain. Explain model and GPU tradeoffs without unexplained technical terms.
- Preserve existing user settings and generated images whenever possible.
- Image-generation work belongs in cancellable background jobs at `/generation-jobs`.
- Keep FastAPI as the LAN endpoint used by ESP32 boards; Electron is only the local desktop shell.
- Add or update automated tests for backend behavior changes.

## Windows installer releases

Any app- or installer-facing change requires a new patch release. Increment the version consistently in:

- `pyproject.toml`
- `src/esp_image_server/app.py`
- `installer/ESPImageServer.iss` (`AppVersion` and `OutputBaseFilename`)

Build in this order:

```powershell
npm --prefix frontend run build
npm --prefix desktop run build
& 'C:\Users\charles\AppData\Local\Programs\Inno Setup 6\ISCC.exe' installer\ESPImageServer.iss
```

The installer is written to `dist\ESPImageServer-Setup-<version>.exe` and should not be committed.

## Pull requests

Describe the user-visible result, list the tests/builds you ran, and call out any ESP32 API or image-format implications. Keep pull requests focused and avoid unrelated formatting or generated-file changes.
