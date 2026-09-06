# TODO

## USB Wi-Fi provisioning

Let users configure a display from ESPImageServer while it is connected by a
USB data cable. Network scanning results, credentials, and setup status travel
over USB serial; the user never needs to join an ESP32 hotspot. After setup,
the display communicates with ESPImageServer over the existing Wi-Fi/LAN
connection. USB can remain connected for power.

### ESP32 firmware (`ESPImageDisplay` repository)

- [ ] Add a shared serial provisioning service for every supported board,
  using native USB CDC or the board's USB-to-UART connection as appropriate.
  Verify the connector and serial configuration for JC4827W543, ST7701
  320x820, ESP32-C6 LCD 1.47, and Cheap Yellow Display.
- [ ] Define a versioned, newline-delimited JSON protocol with request IDs,
  bounded message sizes, structured responses/events, and commands for
  `hello`, `wifi_scan`, `wifi_connect`, `wifi_cancel`, `status`, and
  `wifi_forget`. Distinguish protocol messages from diagnostic logs and
  tolerate partial input, malformed messages, and reconnects.
- [ ] Return the stable hardware ID used for LAN registration, board name,
  firmware version, protocol version, and capabilities in the handshake.
  Status may include the SSID and assigned IP address, never the password.
- [ ] Scan networks asynchronously and return SSID, signal strength, and
  authentication type. Support manual entry for hidden networks and validate
  credentials according to the supported authentication mode.
- [ ] Replace the blocking Wi-Fi connection loop with a state machine that
  keeps USB responsive during scanning, connection attempts, server retries,
  and offline image/video playback. Coordinate Wi-Fi changes with existing
  background tasks to prevent competing connection attempts.
- [ ] Test candidate credentials using an actual new connection, even when
  already connected. Keep previous saved credentials until the candidate
  connects and obtains an IP address; restore the old connection on failure
  or cancellation. Control Wi-Fi driver persistence so failed candidates
  cannot implicitly overwrite working settings.
- [ ] Load saved credentials with `AppConfig::load()` at boot instead of
  unconditionally assigning `WIFI_SSID` and `WIFI_PASSWORD`. Make `secrets.h`
  optional for development builds so distributed firmware needs no personal
  credentials. Persist validated settings safely through power interruption,
  check storage errors, and avoid rewriting unchanged credentials.
- [ ] With no saved credentials, display instructions to connect USB and open
  ESPImageServer. Keep USB setup available for later network changes without
  reflashing, touch input, or working Wi-Fi. Do not automatically start the
  setup hotspot as part of this flow.
- [ ] Report scanning, connecting, obtaining an IP address, Wi-Fi connected,
  finding the server, and ready states. Distinguish authentication failures,
  unavailable networks, and timeouts where driver evidence permits. Save
  valid Wi-Fi credentials even if server discovery fails; report that
  separately and retain the existing server retry behavior.
- [ ] Implement explicit Wi-Fi reset without erasing SD-card content or other
  display settings. Never echo credentials in logs, errors, or status. Update
  firmware setup documentation and credential guidance for this flow.

### Desktop app (`ESPImageServer` repository)

- [ ] Add serial-port access in Electron's main process and a narrow,
  validated preload IPC API for the setup UI. Keep provisioning local to the
  desktop app and retain FastAPI as the display's LAN endpoint.
- [ ] Detect compatible devices using the protocol handshake; identify them
  by hardware ID rather than COM-port number alone. Provide a device/port
  picker for multiple boards or failed automatic detection, and explain when
  installed firmware needs a provisioning-capable update.
- [ ] Add a **Set up display over USB** flow: select the detected display,
  choose a scanned network or enter a hidden SSID, enter the password, and
  connect. Explain supported Wi-Fi bands and authentication modes in plain
  language. Allow retry, cancellation, changing Wi-Fi, and confirmed Wi-Fi
  reset. Browser-only sessions should explain that USB setup uses the desktop
  app.
- [ ] Show live progress and separate **Wi-Fi connected** from **Server
  found**. Match the USB hardware ID to LAN registration before marking the
  display ready. Offer server discovery troubleshooting without asking users
  to re-enter a working Wi-Fi password.
- [ ] Handle unplug/replug, COM-port changes, boot logs, timeouts, port-in-use
  errors, missing drivers, and charge-only cables. Avoid deliberate DTR/RTS
  reset toggles, tolerate boards that reset on port open, and release ports
  after setup and on app shutdown so firmware upload remains possible.
- [ ] Keep passwords out of app logs, analytics, and persistent desktop
  storage; clear temporary password state after completion or cancellation.
- [ ] Include serial dependencies in desktop packaging and document any
  board-specific driver requirements. Rebuild the installer only when asked.

### Verification and acceptance

- [ ] Verify first-time setup, reboot/power-loss persistence, network changes,
  wrong passwords, missing/hidden/open networks, cancellation, and restoration
  of previous working credentials.
- [ ] Verify USB disconnects during setup, reconnect/status recovery,
  multiple boards, unsupported firmware, malformed/oversized protocol input,
  and storage-write failure handling.
- [ ] Verify Wi-Fi settings persist while the server is unavailable and the
  display registers automatically once the server becomes reachable.
- [ ] Check USB responsiveness during offline slideshow/video playback and
  failed server retries. Confirm normal LAN image delivery remains intact.
- [ ] Test the desktop setup UI and packaged serial support on Windows with
  each supported board/USB transport. The user compiles and flashes firmware
  manually; do not build firmware or the installer as part of this TODO update.

## Browser UX review — 2026-09-06

Reviewed the running app reporting v1.0.62 at `http://127.0.0.1:8000`,
including desktop and 390×844 phone layouts. These are observed behavior and
design follow-ups; implementation causes have not been verified.

1. **P1 — Validate empty image prompts and show readable API errors.**
   Submitting an empty image prompt through **Add image to queue** displayed
   `Could not generate the image: [object Object]`. Prevent empty/whitespace
   submissions, show “Enter an image description” beside the prompt, and
   translate structured API errors into useful messages. Verify that an
   invalid submission adds no job and does not obscure an existing job's
   progress or cancellation state.

2. **P1 — Explain model loading and pending cancellation.** The SD-Turbo
   test job remained at “Preparing image generation — 0%” for several
   minutes; only Diagnostics explained that the model was loading on CUDA.
   Surface the actual stage and elapsed time in generation and Queue views.
   Explain when cancellation must wait, keep status consistent across views,
   and confirm when cancellation finishes. The test job was still cancelling
   at the last review check; successful generation and completed cancellation
   remain unverified. Do not assume the model loader is permanently stuck.

3. **P1 — Reconcile SD-card refresh acknowledgements, results, and errors.**
   Refreshing the active display's SD card produced a completed status in the
   header, followed by an error saying the updated list had not arrived. The
   error remained after the list timestamp updated and also appeared on the
   Generate image page. Distinguish “request acknowledged” from “list
   updated,” clear resolved errors when a fresh list arrives, and scope
   feedback to the relevant display and operation. Verify delayed list
   delivery and timeout recovery.

4. **P2 — Make desktop Creation Library filters readable.** With the library
   pinned at its observed width, all three filter labels were truncated to
   “Filt…”. Use short labels such as **Model**, **Display**, and **On SD card**,
   or stack filters when the pane is narrow. Keep the active display context
   available without putting its full name inside every narrow field. Check
   selected values and clear controls at desktop and phone widths.

5. **P2 — Label SD-card actions and use consistent library terminology.**
   The SD-card row action buttons exposed no accessible names. Add specific
   names such as “Show on display” and “Delete file,” with tooltips and enough
   row context to distinguish files for assistive technology. Rename visible
   “Creation Gallery” references, including automatic-save controls, to
   **Creation Library**. Verify keyboard and screen-reader discoverability.

6. **P2 — Put the prompt first and simplify generation settings.** The
   image form puts model, rotation, and automatic saving before the prompt;
   steps and seed also lengthen the phone workflow. Move the prompt to the
   beginning and group secondary controls such as seed, steps, and rotation
   in an expandable settings area. Keep selected settings discoverable and
   make the primary generation action easy to reach on phones. This is a
   design recommendation, not a reproduced functional failure.

Library filtering, saved-image previews, and Escape-to-close worked during
the review. The original prompt, thumbnail view, desktop viewport, and
pinned library state were restored after testing.

## Mobile frontend review

1. **P2 — Add a mobile visual/regression test pass.** Check at 390×844
   portrait, 844×390 landscape, and a notched iPhone Safari view. Cover
   opening and closing the Creation Library, navigation, long display names,
   and the Queue, Diagnostics, and result-action layouts.

## Multi-display UX follow-ups

5. **P2 — Improve physical display identification.** Support friendly room
   names and expose a short hardware/MAC suffix in the chooser for displays
   with similar names.

## Backend and installer hardening

1. **P1 — Bound completed-job, command, and conversion-cache retention.**
   Generation results, display-command acknowledgements, and converted MJPEG
   files accumulate in memory or on disk until a user clears them or removes
   files manually. Add size/count/age limits, safe cleanup at startup and
   shutdown, and tests proving active jobs and referenced media are never
   removed prematurely.

2. **P1 — Apply input-size and media-validation limits at API boundaries.**
   Several endpoints read full request bodies or open untrusted image files
   without a shared maximum byte/pixel policy. Enforce request-size limits,
   validate JPEG decoding and dimensions before storing or processing files,
   and return clear 4xx errors. Test oversized, truncated, and decompression-
   bomb-style images.

3. **P2 — Serialize and atomically publish display MJPEG conversions.**
   Concurrent requests for the same saved video can run FFmpeg twice and write
   the same cache file. Add a keyed conversion lock, write to a temporary file
   then rename it, and remove partial files after failure or cancellation.

4. **P2 — Sign and verify release artifacts.** Add Windows code signing for
   the installer and packaged executable, then document verification of the
   published SHA-256 checksum. This reduces SmartScreen friction and makes a
   downloaded installer verifiable.

## Plan the Hugging Face major-version upgrade

Do not upgrade `transformers` 5.x or `huggingface-hub` 1.x independently.
Treat them as one planned upgrade with Diffusers and the supported image/video
models.

- Upgrade and test `diffusers`, `transformers`, and `huggingface-hub` together.
- Replace removed Hub 1.x `snapshot_download` options, especially
  `local_dir_use_symlinks=False` in `src/esp_image_server/video_generator.py`.
- Review Hub 1.x HTTP, proxy, and exception-handling changes before updating
  download progress or user-facing error messages.
- Confirm model downloads still work on Windows without Developer Mode or
  administrator privileges.
- Test image generation with DreamShaper, SSD-1B, SDXL, and SD-Turbo.
- Test video generation with LTX, Wan, and Hunyuan, including the saved-image
  first-frame path and model download/caching behavior.
- Run the backend test suite, frontend build, and a manual GPU smoke test for
  each model family before releasing the dependency upgrade.
