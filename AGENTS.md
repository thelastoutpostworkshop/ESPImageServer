# ESPImageServer agent guide

## Projects and scope

- Server and web app: `C:\Users\charles\Desktop\Repo\ESPImageServer`
- ESP32 firmware: `C:\Users\charles\Desktop\Repo\JC4827W543_ai`
- The ESP32 firmware is a separate repository. Do not change it for a server-only task, but always consider whether an API or image-format change affects it.

## Architecture

- Backend: FastAPI in `src/esp_image_server`.
- Web app: Vue 3, Vite, and Vuetify in `frontend`.
- The app serves `frontend/dist` in development and packages that bundle in the Windows installer.
- `desktop` contains the Electron shell. It starts and stops the local Python server, provides native folder actions through preload IPC, and loads `http://127.0.0.1:8000` in its window. Keep FastAPI as the LAN endpoint for the ESP32.
- Models are managed through `/models`; model selection is persistent on the server.
- Image generation uses background jobs at `/generation-jobs`. Jobs support progress polling and `DELETE /generation-jobs/{id}` cancellation.
- Generated JPEGs are stored in the configured local image library. Its `image_library_index.json` is kept separately in `%LOCALAPPDATA%\ESPImageServer` so the visible image folder contains only user images.

## ESP32 display contract

- There is currently one active display. A board registers itself with `POST /display` using its name and native `width` and `height`.
- ESP32 boards poll `GET /latest.jpg` and use the ETag to avoid re-downloading unchanged images.
- Keep `/latest.jpg` a baseline JPEG at the announced native display dimensions. ESP32 firmware should not need to transform it.
- Server-side image rotation is configured through `GET`/`PUT /display-settings` with `rotation` of `0`, `90`, `180`, or `270`.
  - The server generates to the correct pre-rotation aspect ratio, rotates the artwork, then exports a JPEG at the display's native dimensions.
  - The web preview counter-rotates the delivered JPEG so it represents the physical display orientation.
  - Do not add matching image rotation in firmware unless the protocol is deliberately redesigned.

## Firmware notes

- `FirmwareTarget.h` selects the board firmware target:
  - `FIRMWARE_TARGET_JC4827W543`: 480x272, GT911 touch.
  - `FIRMWARE_TARGET_ST7701_320X820`: 320x820, no touch.
- Touch is abstracted through `Touch`; use `FIRMWARE_TARGET_HAS_TOUCH` and `ActiveTouch`, not a board-specific controller in shared application code.
- The ST7701 profile must not depend on `TAMC_GT911`; JC-specific touch code is conditionally compiled.
- ESP32 server connection retries use a fixed 5-second interval. Failed display registration also retries after 5 seconds; successful registration refreshes once per minute.
- Wi-Fi credentials stay in ignored `secrets.h`. Target-specific server URL, display name, dimensions, and target selection belong in `FirmwareTarget.h`.

## Installer and releases

- For any app or installer-facing change, rebuild the installer automatically.
- Increment the patch version consistently in:
  - `pyproject.toml`
  - `src/esp_image_server/app.py`
  - `installer/ESPImageServer.iss` (`AppVersion` and `OutputBaseFilename`)
- Build the frontend first:

  ```powershell
  npm --prefix frontend run build
  ```

- Build the Electron bundle before compiling the installer:

  ```powershell
  npm --prefix desktop run build
  ```

- Build the installer:

  ```powershell
  & 'C:\Users\charles\AppData\Local\Programs\Inno Setup 6\ISCC.exe' installer\ESPImageServer.iss
  ```

- Output is `dist\ESPImageServer-Setup-<version>.exe`.
- Track `installer/ESPImageServer.iss`, installer scripts, and assets. Do not track installer output, logs, virtual environments, model caches, or `secrets.h`.

## Verification

- Frontend: `npm --prefix frontend run build`.
- Backend tests: `pytest` when the project Python environment and dependencies are available. If they are not, report that clearly; do not install unrelated dependencies without approval.
- Firmware: use the Arduino CLI profile in `JC4827W543_ai/sketch.yaml`. Compile the relevant target before handoff when practical.

## Collaboration preferences

- Preserve existing user changes and do not reveal credentials from `secrets.h`.
- Keep maker-facing language plain: explain GPU requirements and model tradeoffs without unexplained jargon.
- Every final handoff must include short commit comments for both projects, even if one has no changes:

  ```text
  App commit comment: ...
  ESP32 commit comment: ...
  ```
