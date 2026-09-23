# TODO

## Firmware and USB setup — remaining work

### Firmware reliability review — 2026-09-12

Source review of the separate ESPImageDisplay repository. The three P1 source
changes are implemented for firmware 1.1.6 and app 1.0.76, with transaction/parser
assertions and app tests. The four P2 reliability improvements are implemented for
firmware 1.1.7: content restoration after recovery, checked atomic offline
settings, persistent SD save ordering, and rollover-safe
scheduling. Board selection remains manual in FirmwareTarget.h with the matching
Arduino Maker Workshop profile, as requested by the user. Completed source items have
been removed from this list. Their hardware acceptance checks remain below;
automated checks do not establish recovery on a real board/card.
Settings-preserving updates remain under Updates and distribution.

Current firmware waits for server contact at startup and activates a saved
experience after a 5-second grace period once failed contact is detected. Previous
Waveshare ST7701 320x820 logs confirmed activation with the old 30-second delay
and return to server control on reconnection. The shorter delay, video playback during an outage,
interrupted operations, and equivalent behavior on other boards still need
hardware validation below.

### Video playback performance - remaining work

The completed instrumentation, background HTTP/mDNS worker, buffered SD reads,
inventory-report cache, independent offline timer, and frame-scheduling fix have
been removed from the implementation checklist. On Waveshare ST7701 320x820,
the same 15 FPS clip improved from roughly 3.2–3.4 FPS to 7.8 FPS, then 13.1 FPS
in firmware 1.1.11. The latest capture contains one full five-second playback
window: about 11 ms read/parser time and 62.4 ms decode/draw time per frame.
This establishes improvement, not sustained 15 FPS or video performance during
network failures.

- [ ] **Optimize JPEG decoding and display drawing:** This is now the largest
  measured cost. Separate decode work from display-write time to identify where
  the roughly 62 ms is spent, then optimize the relevant board implementation.
  Preserve image dimensions, colors, and visual quality. Compare sustained FPS
  with the same clip; 15 FPS requires an entire frame budget of about 66.7 ms.
- [ ] **Validate sustained playback during network failures:** Save **Video
  Loop**, rather than Slideshow, and capture longer runs with the server online,
  unavailable, and recovering. Compare full `[Playback]` windows and correlate
  them with `[Network]` timings. Confirm failed requests do not produce long
  playback gaps, offline transitions remain correct, and recovery does not
  cause catch-up bursts. The latest outage logs exercised a slideshow, not
  video. Follow `ESPImageDisplay/tests/README.md` and repeat on all four boards.
- [ ] **Cache playlist ordering:** Inventory reports are already cached, but
  selecting the next video still scans the directory and ordering metadata.
  Cache playlist selection with bounded memory, updating it after saves,
  deletions, card changes, and explicit refreshes. Preserve newest-first,
  oldest-first, and random order without immediate repeats when alternatives
  exist. Measure pauses between clips with a large library.
- [ ] **Validate the inventory cache under load:** Refresh a large SD library
  during playback; save/delete files and remove or replace the card. Check
  report freshness, memory use, out-of-memory handling, and command response
  time. Normal periodic registration should not trigger another directory scan.
- [ ] **Reuse playback buffers:** Retain a compressed-frame buffer across
  playlist entries instead of allocating/freeing it for every video. Define
  when memory is released and measure transition pauses and heap fragmentation
  over long runs, especially on boards without PSRAM.
- [ ] **Evaluate next-frame prefetch where memory allows:** The 2 KiB input
  buffer is implemented; preparing another complete compressed frame ahead of
  time is not. Assess this after profiling rendering, and retain coordinated
  SD/display access on shared-SPI boards. Do not assume that another buffer
  alone will overlap synchronous decoding/drawing.
- [ ] **Finish screen-update coordination:** Routine connection errors no
  longer overwrite an active video, but audit the remaining status/setup/error
  paths. Ensure explicit commands and necessary errors take precedence without
  incidental background updates replacing playback content.

Keep SD access and drawing coordinated; some targets share an SPI bus. The
command interruption, USB setup, and card-removal checks below also apply during
video playback. The user builds and flashes firmware manually.

### Hardware validation

- [ ] **Connected experience and save interruption:** Boot with an experience
  saved and ESPImageServer running. Confirm the display waits for commands and
  accepts image saves. Stop the server for over 5 seconds to start fallback;
  restart it and save an image during playback. Confirm playback stops, the app
  reports server-controlled mode and the save completes. Repeat saving during an
  explicitly requested preview; that preview must stop and stay stopped.
- [ ] **Current firmware board acceptance:** Manually compile and flash using
  the Arduino Maker Workshop extension after setting `FIRMWARE_TARGET` in
  `FirmwareTarget.h` and choosing the matching compile profile. Confirm the physical display,
  USB identity, dimensions, version and package target agree on all four boards.
  Restart the server/router while showing an unchanged live image, then repeat
  with a manually selected SD image/video; restore the selection rather than
  leaving a connection message. A video may restart from its beginning.
- [ ] **Offline settings storage:** Verify unsupported settings records are rejected,
  save/reboot, preview without saving, failed storage and power interruption
  during replacement. Failure must not receive a saved confirmation or mix
  settings. Confirm Wi-Fi and SD files survive. Software assertions cover the
  storage-result boundary; physical NVS interruption remains unverified.
- [ ] **Slideshow chronology:** Save images/videos in a different order from
  their filenames; check newest-first/oldest-first and wrap before/after reboot,
  retrying an existing save and thumbnail completion. Include a damaged/missing
  `.order` record. Files without valid ordering metadata use deterministic
  filename fallback; saved files use their persistent card sequence.
- [ ] **Long uptime and interruption:** Exercise retries, SD remount, polling,
  slideshow/video playback and stalled downloads across `millis()` rollover on
  hardware or an instrumented build. Automated assertions cover wrap, expiry at
  zero and a late loop; normal hardware timing remains to be verified.

- [ ] **Adaptive status messages:** Manually compile and flash the new status
  layout on JC4827W543, ST7701 320x820, ESP32-C6 LCD 1.47, and Cheap Yellow
  Display. Check physical readability of startup, USB Wi-Fi setup, connection
  errors, and SD-card messages, including long filenames and firmware versions.
  Layout assertions and pixel previews do not replace a real-screen check.
- [ ] **Complete board coverage:** Test the current flash/boot/USB setup flow on
  Cheap Yellow Display. On C6 and ST7701, verify unplug/replug identification,
  saved Wi-Fi after a power cycle, and Forget Wi-Fi followed by reprovisioning,
  preserving SD files and other settings. Complete the recovery tests below on
  all four boards.
- [ ] **Bootloader and flashing recovery:** Verify automatic bootloader entry
  and manual BOOT/RESET recovery on each board, first installation without
  compatible firmware, occupied/missing ports, interrupted writes, and port
  release after success, failure, and app shutdown. Record the working data
  connector and reset sequence for each board.
- [ ] **USB identification failures:** Test a busy port, disconnect during
  identification, unsupported firmware, and malformed/oversized serial input.
  Confirm recovery without stale identity or an incorrect board selection.
- [ ] **Wi-Fi failure cases:** Verify wrong passwords, unavailable/hidden/open
  networks, cancellation, changing networks, rollback to previous working
  credentials, storage failures, USB interruption, and interrupted credential
  replacement. Check that USB stays responsive during server retries and
  offline slideshow/video playback.
- [ ] **Network recovery and LAN delivery:** Test setup while the server is
  unavailable, server/router restart, and automatic reconnection without
  re-entering Wi-Fi credentials. Verify normal image delivery after setup and
  after recovery on each board.
- [ ] **Multiple devices:** Connect several boards and swap devices/COM ports.
  Verify that USB setup, Ready status, and image/SD-card commands remain bound
  to the selected physical display.
- [ ] **SD-card delays and recovery:** Measure card-refresh, image download,
  card-write, verification/commit, thumbnail, acknowledgement, and file-list
  times using the new serial timings to explain the delayed Waveshare save.
  Manually compile/flash the current firmware on all four targets. Test power cuts before/during
  rename, removal/reinsertion during download/verification, no/full card, retry
  over a legacy partial file, and delayed reports. A partial file must never
  receive a saved confirmation. Verify the main acknowledgement precedes
  thumbnail completion/failure and refreshes the file list in the updated app.
- [ ] **P1 responsiveness hardware acceptance:** During a long MJPEG preview,
  use Stop preview and a replacement command. Stall a download, cancel while
  waiting for headers and during verification, then retry immediately and after
  workers settle. Measure LAN response time and confirm USB Wi-Fi setup and
  card-removal checks remain responsive. Test late acknowledgements and changing
  the active display while saving; progress/cancellation must stay on the
  original board. Confirm recovery without waiting for the whole video/transfer.

### Updates and distribution

- [ ] **Settings-preserving updates:** Define update packages separately from
  first-install packages. Preserve Wi-Fi/display settings and NVS, account for
  merged-binary padding, detect partition-layout changes, and explain required
  migrations or resets. Test settings preservation and interrupted-update
  recovery; keep full erase/factory reset an explicit choice.
- [ ] **Offline release bundle:** Bundle tested firmware packages for all four
  boards. Verify the packaged esptool and serial dependencies on Windows without
  a separate Arduino/Python installation, including driver, charge-only cable,
  port-change, and port-in-use cases. GitHub downloads are available; an offline bundle remains optional.
- [ ] **Board and release documentation:** Document the tested connector,
  BOOT/RESET procedure, drivers, and build profile for each board; add model
  pictures for manual selection. Publish versioned firmware packages with
  accurate release notes and complete a packaged-app hardware pass. The user
  compiles firmware manually; rebuild the desktop installer only when requested.

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

2. **P1 — Reconcile SD-card refresh acknowledgements, results, and errors.**
   Refreshing the active display's SD card produced a completed status in the
   header, followed by an error saying the updated list had not arrived. The
   error remained after the list timestamp updated and also appeared on the
   Generate image page. Distinguish “request acknowledged” from “list
   updated,” clear resolved errors when a fresh list arrives, and scope
   feedback to the relevant display and operation. Verify delayed list
   delivery and timeout recovery.

3. **P2 — Make desktop Creation Library filters readable.** With the library
   pinned at its observed width, all three filter labels were truncated to
   “Filt…”. Use short labels such as **Model**, **Display**, and **On SD card**,
   or stack filters when the pane is narrow. Keep the active display context
   available without putting its full name inside every narrow field. Check
   selected values and clear controls at desktop and phone widths.

4. **P2 — Label SD-card actions and use consistent library terminology.**
   The SD-card row action buttons exposed no accessible names. Add specific
   names such as “Show on display” and “Delete file,” with tooltips and enough
   row context to distinguish files for assistive technology. Rename visible
   “Creation Gallery” references, including automatic-save controls, to
   **Creation Library**. Verify keyboard and screen-reader discoverability.

5. **P2 — Put the prompt first and simplify generation settings.** The
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

## Linux and macOS support preparation

Preparation only: retain Windows support and the current no-CPU-generation
policy. Keep display management available independently of AI generation.

### First milestone: code readiness

Complete this milestone before starting native installers or announcing support.
The platform abstractions and hosted CI checks below are implemented. Preserve
Windows behavior as platform delivery progresses.

- [x] **P1 - Automated desktop runtime and lifecycle validation:**
  Runtime/tool resolution is isolated in `desktop/runtime.mjs`; Windows paths
  are preserved, with explicit missing-runtime errors, owned-server shutdown,
  and macOS window reopening. Automated tests cover these behaviors. User-confirmed
  Windows desktop checks passed: startup with saved content, owned-server shutdown
  and restart, preserving an independently started server, and focusing the
  existing window on a second launch. Real Electron/Python smoke tests passed
  on Windows 2025, Ubuntu 24.04, and macOS 15 hosted runners, confirmed by the
  user for commit `069b500`. These cover actual startup/quit, Vue
  rendering, preload IPC, owned-server exit/port release, external-server
  preservation, and macOS activation after closing the window. Both server
  ownership scenarios also passed locally on Windows. The local
  run logged an mDNS advertisement timeout but completed startup; this does not
  establish LAN discovery behavior.
  Non-Windows runtime/tool bundles and installers remain a later milestone.
- [x] **P1 - Validate writable paths on native Linux/macOS:** Shared path
  resolution is implemented in `paths.py`, with Windows locations preserved and
  unit coverage for all three platforms, XDG overrides, Unicode/spaces, and
  explicit library/model-cache paths. Hosted checks verified persistence using
  native filesystem behavior and a read-only installation directory on Linux/macOS.
  A native-storage CI check now saves settings and a fixture image, then verifies
  them in a fresh backend process using actual host path rules, spaces/Unicode,
  and isolated user storage. Linux also exercises custom XDG directories.
  Linux/macOS enforce read-only permissions on a copied source installation;
  all platforms guard Python file writes and verify the installation is unchanged.
  Windows persistence passed locally. The user confirmed the hosted action passed
  on Windows, Ubuntu, and macOS after correcting the test's null-device handling.
  These checks do not exercise packaged installation or real model downloads.
- [ ] **P1 - Complete Windows USB UI verification:** Shared
  `desktop/serial-ports.mjs` now enumerates Windows, Linux, and macOS serial paths
  through SerialPort.list(), replacing PowerShell enumeration. Selection checks
  the detected list; identification, flashing, and Wi-Fi setup recheck presence
  before opening. Automated tests cover native path formats, firmware release
  selection, simulated flashing/setup, disappearance, and device identity checks.
  Windows hardware checks passed through the shared desktop modules on COM26
  (Waveshare 3.16inch, firmware 1.1.13): enumeration, physical unplug/replug,
  identification, identity refresh, Wi-Fi scanning, and reopening after scanning.
  Initial access denial cleared after releasing the port; identification then
  timed out until a USB reconnect. The timeout cause remains unconfirmed.
  Still verify the Windows Electron UI flow (native UI automation was unavailable).
- [ ] **P1 - Complete Windows native folder-action verification:** Folder actions
  are isolated in `folder_actions.py`, with capability reporting, Windows chooser,
  Windows/macOS/Linux folder opening, and explicit unsupported-action errors.
  Electron retains its native dialogs. Settings allows manual server-side path
  entry when a chooser is unavailable. Adapter/API tests cover fallback, cancel,
  overrides, and validation. Actual Windows dialogs/opening remain to be checked.
  Added desktop smoke coverage through real preload/IPC for selection, cancel,
  native errors, and preservation of the saved library path; OS dialog/opener
  calls are stubbed. Backend checks cover Wayland, missing macOS opener, headless
  API/manual-path fallback, and opener failures/timeouts. The user confirmed this
  added coverage passed in CI on Windows, Ubuntu, and macOS.
  Use CONTRIBUTING.md's folder checklist for the remaining Windows checks.
- [x] **P1 - Verify the readiness boundary:** The `Platform checks` GitHub Actions
  workflow runs backend tests, frontend tests/build, and desktop module tests on
  Windows, Ubuntu, and macOS. Tests cover platform paths, runtime resolution,
  serial-port validation, native-action availability, management-only startup,
  and a real bundled-FFmpeg encode/decode. Test storage is isolated before app
  imports. The user confirmed a successful hosted CI run on Windows, Ubuntu,
  and macOS. CI mocks GPU pipelines and USB devices; it does not establish
  packaged desktop, native-dialog, or real GPU/USB behavior.
  Preserve the ESP32 LAN API, GPU serialization, and cancellation behavior.
  Windows GPU smoke check confirmed by the user after the capability refactor
  and dependency repair: video generation completed, followed by successful
  image generation, validating MP4 export and the video-to-image GPU handoff.

### Later milestone: platform delivery

- [x] **P1 - Define the support matrix:** Initial scope is documented in
  PLATFORMS.md: retain Windows x64, target Ubuntu 24.04 x64 with NVIDIA CUDA and
  display management, and macOS 15+ Apple Silicon with display management only.
  Intel Macs and Linux ARM64 are deferred; CPU/MPS generation stays disabled.
  CI explicitly checks Python/Node platform and architecture. The user confirmed
  the updated workflow passed on Windows x64, Ubuntu x64, and macOS ARM64.
  Linux/macOS directory bundles are implemented; final distribution formats remain.
- [x] **P1 - Package dependencies per OS and architecture:** Native standalone
  Python, Electron/serialport, esptool, and FFmpeg bundles and hosted tests are
  implemented. Earlier management and CUDA bundles passed CI. Linux now ships
  only a small base installer with first-launch dependency download; macOS
  remains management-only. Windows installation is unchanged.
- [x] **P1 - Verify automatic Linux generation setup in CI:** The desktop now
  checks NVIDIA availability, automatically downloads pinned generation
  dependencies into private user storage, verifies them, and starts the service.
  The startup screen provides progress, retry, and an explicit unsupported-GPU
  fallback. Verified dependencies survive app-only updates. CI exercises actual
  downloads, offline reuse, pipeline imports and no-GPU startup; packaged checks
  exercise the GPU-unavailable UI. Local failure/retry/reuse tests pass.
  The user confirmed the hosted checks passed. No intermediate backend/desktop
  archives or separate Linux management/CUDA installers are uploaded.
- [x] **P1 - Prepare USB setup and firmware flashing:** Package the matching
  esptool executable and handle native serial-device names. Document Linux
  serial permissions/udev setup and macOS driver requirements where applicable.
  Keep automated identification, flashing, and port-lifecycle coverage.
  Keep permissions narrowly scoped; do not require running the whole app as root.
  Pinned esptool 5.1.0 archives for Linux x64/macOS ARM64 are now verified and
  included by the native bundle build. CI checks the bundled version and actual
  serialport enumeration. The user confirmed both native jobs passed.
  USB_SETUP.md now covers Ubuntu group permissions, device-specific udev rules,
  the udevadm dependency, macOS driver selection, and connection troubleshooting.
- [ ] **P2 - Add native distribution and update flows:** Choose Linux package
  formats and macOS application packaging, icons, signing/notarization, and
  permissions. Build on appropriate native runners. Define install, update,
  repair, and uninstall behavior that preserves settings and user creations.
  Keep pyproject.toml as the version source and publish per-platform checksums.
  Versioned desktop tar archives and adjacent SHA-256 files are implemented for
  Linux management/CUDA and macOS management bundles. CI verifies archived
  contents, permissions, and symlinks before upload; focused tests cover archive
  extraction and reject version mismatches. The user confirmed the hosted
  archive and checksum checks passed on Linux and macOS.
  Native Ubuntu .deb and macOS .dmg installer lifecycle checks passed, confirmed
  by the user. Linux packaging now uses a single base installer with automatic
  generation setup. NATIVE_INSTALL.md documents the new download/setup behavior.
  Signing/notarization, cross-version migration, and automatic updates remain open.
- [x] **P1 - Confirm automated upgrade preservation checks:** Implemented a
  synthetic 0.0.1-to-current upgrade on Windows (real Inno script with fixture
  bootstrap/desktop payload), Ubuntu (apt), and macOS (app replacement). Verify
  the installed version and load saved settings/content with the current backend.
  Linux also tests failed dependency updates without losing the previous runtime.
  Local tests and the hosted Windows, Ubuntu, macOS, and Linux dependency recovery
  checks passed; hosted success confirmed by the user.
  This is package replacement coverage, not historical schema migration coverage.
- [x] **P1 - Add automated cross-platform release checks:** Extend the existing
  backend/frontend/Electron CI matrix to packaged-app startup and supported
  architectures. Keep Windows manual acceptance checks.
  Native directory-bundle build, relocation, and packaged Electron smoke checks
  passed for Linux x64 and macOS ARM64, confirmed by the user.

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
- Test image generation with DreamShaper, SSD-1B, and SDXL.
- Test video generation with LTX and Wan, including the saved-image
  first-frame path and model download/caching behavior.
- Run the backend test suite, frontend build, and a manual GPU smoke test for
  each model family before releasing the dependency upgrade.
