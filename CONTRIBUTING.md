# Contributing to ESPImageServer

Thanks for helping improve ESPImageServer. This project creates locally generated images for ESP32 displays. Keep changes practical, reliable, and friendly for makers.

## Project layout

- `src/esp_image_server/` — FastAPI server and image-generation logic.
- `frontend/` — Vue 3, Vite, and Vuetify web application.
- `desktop/` — Electron desktop shell for the local server and native folder actions.
- `installer/` — Windows installer sources.
- `tests/` — backend API and image-processing tests.

The ESP32 firmware lives in the separate `ESPImageDisplay` repository. Do not change it for server-only work, but consider it whenever changing an API or the JPEG format.

## Development setup

Use Python 3.10 or newer and a recent Node.js LTS release.

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
