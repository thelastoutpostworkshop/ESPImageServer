# Contributing to ESPImageServer

Thanks for helping improve ESPImageServer. This project creates locally generated images for ESP32 displays. Keep changes practical, reliable, and friendly for makers.

## Project layout

- `src/esp_image_server/` — FastAPI server and image-generation logic.
- `frontend/` — Vue 3, Vite, and Vuetify web application.
- `desktop/` — Electron desktop shell for the local server and native folder actions.
- `installer/` — Windows installer sources.
- `tests/` — backend API and image-processing tests.

The ESP32 firmware lives in the separate `JC4827W543_ai` repository. Do not change it for server-only work, but consider it whenever changing an API or the JPEG format.

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
