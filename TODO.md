# TODO

## USB firmware flashing and Wi-Fi provisioning

Implement and test these milestones in order. The first deliverable is flashing
firmware from ESPImageServer on one supported board. Complete its hardware test
before moving on to USB provisioning; Wi-Fi setup is not a prerequisite for
that first test. Checked items are implemented; hardware acceptance is tracked
separately and remains required before advancing to USB provisioning.

Final user flow: **Connect USB -> Install firmware -> Set up Wi-Fi -> Ready**.
Firmware installation, network scan results, credentials, and setup status use
the USB data cable. Users never need to join an ESP32 hotspot. Normal display
communication continues over Wi-Fi/LAN, and USB can remain connected for power.

### Step 1 - Flash firmware from ESPImageServer (first testable milestone)

Scope: one user-selected supported board, a local precompiled firmware package,
and a desktop flashing screen. Automatic model recognition, Wi-Fi provisioning,
and online firmware downloads are not required for this milestone.

- [x] **Firmware package:** The user manually compiles the selected board in
  `ESPImageDisplay` and supplies its binaries and actual build flash arguments.
  Define a package manifest with board target, chip type, firmware version,
  flash size/settings, binary offsets, and SHA-256 checksums. Include all
  components required for first installation, not just the application binary.
  Do not guess offsets or distribute firmware containing personal credentials.
- [x] **Desktop flashing service:** Include a pinned Windows esptool executable
  and invoke it from Electron's main process using structured arguments and a
  narrow, validated preload IPC API. Run it asynchronously with progress and
  error reporting. Keep flashing local to the desktop app; retain FastAPI as
  the display's LAN endpoint. No Arduino IDE/compiler is required on end-user
  machines, and esptool must not depend on a system PATH installation.
- [x] **Minimal flashing screen:** List serial ports, let the user select the
  board model and local firmware package, and show the target/version before
  **Install firmware**. Validate checksums, package paths/offsets, detected chip,
  and flash capacity before writing. Chip detection alone cannot distinguish
  different display boards using the same ESP32 chip.
- [ ] **Bootloader and port handling:** Use esptool's appropriate reset sequence
  to enter the built-in ROM bootloader. Provide board-specific BOOT/RESET and
  connector instructions if automatic entry fails. Exclusively own the port
  during flashing, handle a busy/missing port, and release it on completion or
  failure. First installation must work without existing ESPImageDisplay code
  or the future USB provisioning handshake.
- [x] **Write and verify:** Show connecting, writing, verifying, and restarting
  states. Check process exit status and successful flash verification; do not
  report a successful write as proof the application booted. Avoid full-chip
  erase by default and explain any required settings loss before installation.
  Give retry/recovery instructions after an interrupted write.
- [x] **First hardware test (flash and boot confirmed by user on 2026-09-12):** From the running ESPImageServer desktop app,
  install the supplied package over USB, verify the write, restart the board,
  and confirm expected display startup/version through existing screen or
  serial output. Record board, connector, package version, and reset method.
  User confirmed successful flashing and booting of JC4827W543 from the desktop app. Board-specific failure/recovery checks remain in the bootloader follow-up.

**Advance when:** The user has successfully flashed and booted the selected
board from ESPImageServer. No Wi-Fi provisioning implementation is required to
pass this milestone. If automatic boot identity is unavailable, record the
manual boot/version check separately from the tool's write verification.

Implementation check: the desktop **Install firmware** page accepts local
manifest packages and runs pinned esptool 5.1.0 with checksum/chip/layout checks,
exclusive installation jobs, logs, and write verification. Hardware-free tests
cover validation failures and process recovery. Manual board-specific connector/
reset guidance and the first real flash/boot test still need hardware validation.
The built-in Browser was unavailable for the live UI check during implementation.

### Step 2 - Identify the running firmware over USB

- [x] **Firmware:** Add a shared serial service using native USB CDC or the
  board's USB-to-UART connection. Start with versioned, newline-delimited JSON
  commands `hello` and `status`, request IDs, bounded message sizes, and
  structured responses/events. Separate protocol messages from diagnostic logs
  and tolerate partial/malformed input. Do not wait indefinitely for USB.
- [x] **Identity:** Return the stable hardware ID used for LAN registration,
  board target/name, firmware version, protocol version, and capabilities.
- [x] **Desktop:** Add serial communication through the validated preload API.
  Close the provisioning connection before esptool runs, then reconnect after
  restart, including COM-port changes. Avoid deliberate reset toggles during
  normal provisioning; reserve bootloader reset sequences for flashing.
- [x] **Discovery:** Identify compatible devices by handshake/hardware ID,
  provide a picker for multiple devices, and offer flashing when firmware is
  missing or unsupported. Preserve the manual model choice for first installs.
- [x] **Hardware identification test (confirmed on 2026-09-12):** Flashed
  JC4827W543 firmware 1.1.2; the desktop app reported startup verified over USB
  on COM8 with hardware ID `a03e0997bacc` and dimensions 480 × 272. User also
  confirmed the correct identification after the unplug/replug test.
- [ ] **Failure/recovery tests:** Verify busy-port and disconnect-during-
  identification recovery, unsupported firmware, and malformed/oversized input.
  Board-specific bootloader and interrupted-write recovery remain in Step 1.

**Advance when:** The app reliably reconnects after flashing and verifies the
running firmware identity, with clear recovery when no handshake arrives.

Implementation: firmware 1.1.2 now serves read-only hello/status requests on USB;
the desktop can identify a selected port and check identity automatically after
flashing. COM changes are followed only when USB serial identity is unique.
Firmware compilation remains manual. The JC4827W543 flash, boot, post-flash
USB identification, and unplug/replug identification have been confirmed;
failure/recovery checks remain open.

### Step 3 - Connect to Wi-Fi and save credentials over USB

- [x] **Firmware:** Add `wifi_scan`, `wifi_connect`, and `wifi_cancel` commands.
  Scan asynchronously and return SSID, signal strength, and authentication
  type. Support hidden-network entry and validate supported credential formats.
- [x] **Connection state:** Replace blocking Wi-Fi connection attempts with a
  state machine. Keep USB responsive during connection, server retries, and
  offline slideshow/video playback. Coordinate background tasks so they cannot
  initiate competing scans or connections.
- [x] **Credential storage:** Load `AppConfig::load()` at boot instead of always
  assigning `WIFI_SSID`/`WIFI_PASSWORD`. Make `secrets.h` optional for development;
  distributed builds contain no personal credentials. Test candidates through
  an actual new connection, even if already connected. Save only after an IP
  address is obtained; preserve and restore previous working settings on
  failure/cancellation. Control Wi-Fi driver persistence, check storage errors,
  make replacement safe across power interruption, and avoid redundant writes.
- [x] **Desktop setup:** Show scanned networks, manual hidden SSID entry,
  password input, Connect, Cancel, and Retry. Explain supported Wi-Fi bands and
  authentication modes. Report scanning, connecting, obtaining an IP address,
  and connected states, with useful errors based on driver evidence.
- [x] **Privacy and first boot:** Never echo passwords in serial responses,
  errors, logs, analytics, or desktop persistent storage. Clear temporary app
  password state on completion/cancellation. With no credentials, show USB
  setup instructions on the display; do not automatically start a hotspot.
- [x] **First Wi-Fi setup (user confirmed on 2026-09-12):** Network selection
  and password entry worked in the desktop app, and JC4827W543 connected to Wi-Fi.
- [x] **Saved Wi-Fi persistence (user confirmed on 2026-09-12):** JC4827W543
  running 1.1.3 reconnects after a power cycle without entering credentials again.
- [ ] **Remaining tests:** Verify wrong password, missing/hidden/open networks,
  cancellation, network changes, rollback, storage failure, USB interruption,
  and interrupted credential replacement. Verify USB remains responsive
  during offline playback and server retries.

**Advance when:** A user can configure Wi-Fi entirely over USB and the board
reconnects after reboot without reflashing or joining a setup hotspot.

Implementation: firmware 1.1.3 and the desktop now implement USB Wi-Fi setup.
Desktop automated tests cover validation, device binding, cancellation, disconnect,
and storage-error responses (43 tests passed). The frontend build passed and a
simulated browser preview verified scanning/connection states and password-field
clearing. The live server at 127.0.0.1:8000 refused the connection during that
initial check. The user subsequently compiled and flashed firmware 1.1.3;
the remaining real-board acceptance checks are listed above.
See `scripts/usb-wifi-setup.md`.

Hardware follow-up (2026-09-12): user flashed JC4827W543 1.1.3 and confirmed
the USB Wi-Fi setup screen. Diagnosed missing serial framing in that build;
fixed firmware serialization and added desktop compatibility. Live identification
on COM8 now verifies 1.1.3, hardware ID `a03e0997bacc`, and Wi-Fi capabilities.
All 44 desktop tests passed at that follow-up. The user subsequently confirmed
successful Wi-Fi setup and power-cycle reconnection after the desktop fixes.
Failure/recovery tests remain open.

### Step 4 - Complete the guided setup and recovery flow

- [x] **Wizard:** Join flashing, post-boot identification, and Wi-Fi setup into
  one flow. Skip flashing when compatible firmware is already installed.
  Browser-only sessions should explain that USB setup uses the desktop app.
- [x] **Server handoff:** Distinguish **Wi-Fi connected** from **Server found**.
  Match USB hardware ID to LAN registration before showing Ready. Save valid
  Wi-Fi credentials even when the server is unavailable; retain existing
  server retries and offer discovery troubleshooting without password re-entry.
- [x] **Change/reset Wi-Fi:** Keep USB setup accessible without working Wi-Fi,
  touch input, or reflashing. Add confirmed `wifi_forget` behavior that clears
  only Wi-Fi settings, preserving SD content and other display settings.
- [x] **JC4827W543 reset and recovery (user confirmed on 2026-09-12):** On
  firmware 1.1.4, Forget Wi-Fi removed the credentials; unplug/replug returned
  to USB Wi-Fi setup without reconnecting. Provisioning again reached Ready.
  SD content and other display settings remained intact.
- [ ] **Remaining hardware tests:** Verify server-unavailable recovery and
  normal LAN image delivery after setup. Test multiple connected devices and
  swapping devices/ports so selection and setup status cannot mix between boards.

**Advance when:** The full USB setup flow reaches the correct LAN-connected
display and explains how to recover at each failed stage.

Implementation (2026-09-12): the desktop Set up display page skips optional
flashing for compatible firmware, matches fresh LAN contact to the USB hardware
ID/version/dimensions, and clears identity when a selected port disappears or
changes. Firmware 1.1.4 adds confirmed Wi-Fi-only reset; older 1.1.3 firmware
supports the guided connection flow but cannot forget Wi-Fi over USB.
Validation: 49 desktop tests and 9 frontend tests passed; frontend build passed.
A simulated browser walkthrough verified compatible-firmware skip, matched
Ready, reset confirmation/cancellation, and returning to setup after reset.
The live browser check at 127.0.0.1:8000 returned connection refused.
Automated tests use simulated devices and server responses. Firmware 1.1.4
was subsequently compiled and tested by the user as recorded below. Remaining
real-board acceptance tests are listed above. No installer was rebuilt during
that implementation.

Hardware follow-up (2026-09-12): user compiled and installed JC4827W543
firmware 1.1.4 and confirmed the display connected. Desktop USB identity reports
1.1.4 on COM8, hardware ID `a03e0997bacc`; the installation log shows all four
writes verified and a hard reset via RTS. The user subsequently confirmed the
complete Forget Wi-Fi, power-cycle, and reprovisioning sequence worked as
expected, reached Ready, and preserved SD content and other settings. This
confirms the normal reset/recovery path on this board; fault-injection and
multiple-device tests remain pending.

### Step 5 - Support all boards and package for distribution

- [ ] **Board matrix:** Repeat flashing, boot verification, provisioning, and
  recovery tests for JC4827W543, ST7701 320x820, ESP32-C6 LCD 1.47, and Cheap
  Yellow Display. Document connectors, reset behavior, drivers, and build
  profiles; include model pictures to simplify manual selection.
- [ ] **Offline release bundle:** Include tested firmware packages, manifests,
  esptool, and serial dependencies in Electron packaging. Verify on Windows
  without a separate Arduino/Python installation, and provide guidance for
  missing drivers, charge-only cables, port changes, and port-in-use errors.
  Release ports on app shutdown. Online firmware downloads can follow later.
- [ ] **Updates versus first installs:** Define compatible update packages that
  preserve Wi-Fi/display settings and avoid writing across their NVS region,
  including padding in merged binaries. Detect partition-layout changes and
  explain migrations or required resets. Keep full erase/factory reset an
  explicit choice; test interrupted-write recovery and settings preservation.
- [ ] **Documentation and release checks:** Update setup instructions and both
  projects' credential guidance. Run relevant builds/tests and a packaged-app
  hardware pass. The user compiles firmware manually; rebuild the installer
  only when requested. This TODO edit itself performs no builds or flashing.

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
