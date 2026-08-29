# ESPImageServer agent guide

## Projects and scope

- Server and web app: `C:\Users\charles\Desktop\Repo\ESPImageServer`
- ESP32 firmware: `C:\Users\charles\Desktop\Repo\ESPImageDisplay`, do not build the ESP32 firmware, the user will do it manually
- The ESP32 firmware is a separate repository. Do not change it for a server-only task, but always consider whether an API or image-format change affects it.

## Architecture

- Backend: FastAPI in `src/esp_image_server`.
- Web app: Vue 3, Vite, and Vuetify in `frontend`.
- The app serves `frontend/dist` in development and packages that bundle in the Windows installer.
- `desktop` contains the Electron shell. It starts and stops the local Python server, provides native folder actions through preload IPC, and loads `http://127.0.0.1:8000` in its window. Keep FastAPI as the LAN endpoint for the ESP32.
- Models are managed through `/models`; model selection is persistent on the server.
- Image generation uses background jobs at `/generation-jobs`. Jobs support progress polling and `DELETE /generation-jobs/{id}` cancellation.
- Generated JPEGs are stored in the configured local image library. Its `image_library_index.json` is kept separately in `%LOCALAPPDATA%\ESPImageServer` so the visible image folder contains only user images.
- Image models expose a negative-prompt field only when supported: DreamShaper 8, SSD-1B, and SDXL. SD-Turbo deliberately does not receive a negative prompt.
- Image and video models share the GPU. Starting one kind of job unloads the other model and clears CUDA cache; do not remove this handoff or allow concurrent image/video generation jobs.

## Video generation and Creation Gallery

- Video generation uses one-worker jobs at `/video-generation-jobs`, with progress polling and cancellation matching image jobs.
- The selectable local LTX checkpoints are `ltxv-2b-0.9.6-distilled-04-25` (fast: 4–8 steps, CFG 1.0) and `ltxv-2b-0.9.6-dev-04-25` (quality: 10–40 steps, CFG 3.0). They are loaded lazily and swapped safely by `LTXVideoGenerator`.
- Do not generate LTX directly at tiny ESP32 dimensions. `working_video_size()` creates a 32-pixel-aligned, aspect-matched working canvas (normally 384 pixels on the short side, max 704 on the long side), then frames are downscaled to the connected display's exact native size.
- A video can be text-only or use a saved Creation Gallery image as its first frame. Preserve the `source_image_id` in video metadata so saved settings can restore that reference image.
- Saved videos live in `<image library>\videos` with an adjacent JSON metadata file. The gallery groups both images and videos by the model name, shows tooltips, and lets the user restore saved video settings from a context menu.
- Video thumbnails are extracted with the executable bundled by the `imageio-ffmpeg` Python dependency; do not rely on a system `ffmpeg` PATH installation. The installer verifies this executable after installing packages. Keep thumbnail failure non-fatal so a video can still be saved if extraction itself fails.

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

- For any app or installer-facing change, do not rebuild the installer, the user will ask to rebuild it.
- `pyproject.toml` is the single source of truth for the version. Update it before a release, then run `./build-installer.ps1`; the script synchronizes Electron and Inno Setup metadata automatically. Do not manually change the derived version values.
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
- Live frontend check: for a visible frontend change, use Codex Desktop's
  built-in Browser to test the running app at `http://127.0.0.1:8000` after
  the frontend build. Navigate to the affected page and inspect the expected
  state and controls. Do not trigger image/video generation, display commands,
  file deletion, or settings changes unless the task specifically requires it.
  If the browser is unavailable, report that the live check was skipped. To
  connect it, enable **Browser** in Codex Desktop Settings > Browser and set
  **Local URL open destination** to **ChatGPT**.
- Backend tests: use `& .\.venv\Scripts\python.exe -m pytest` when the project virtual environment is available. If it is not, report that clearly; do not install unrelated dependencies without approval.
- Firmware: use the Arduino CLI profile in `JC4827W543_ai/sketch.yaml`. Compile the relevant target before handoff when practical.

## Collaboration preferences

- Preserve existing user changes and do not reveal credentials from `secrets.h`.
- Keep maker-facing language plain: explain GPU requirements and model tradeoffs without unexplained jargon.
- Every final handoff must include short commit comments for both projects, even if one has no changes:

  ```text
  App commit comment: ...
  ESP32 commit comment: ...
  ```
