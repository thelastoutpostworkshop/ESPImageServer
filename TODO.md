# TODO

## Firmware and USB setup — remaining work

### Firmware reliability review — 2026-09-12

Source review of the separate ESPImageDisplay repository. The three P1 source
changes are implemented for firmware 1.1.6 and app 1.0.76, with transaction/parser
assertions and app tests. Their physical acceptance checks remain below;
automated checks do not establish recovery on a real card. Remaining source
improvements are P2. Settings-preserving updates remain under Updates and distribution.
- [ ] **P2 — Restore display content after network recovery:**
  `noteServerContact()` clears `connectionProblemActive` before the
  unchanged-image recovery branch checks it. Track connection state
  separately from the content currently drawn, and restore the image after
  recovery without overwriting a manual SD selection. Test a temporary server
  outage followed by an unchanged-image response; an error screen must not
  remain visible after reconnection.
- [ ] **P2 — Verify offline settings persistence:** `saveDisplayMode()`
  ignores Preferences write results, while its caller unconditionally
  reports success. Check storage results and persist the related settings
  together, following the versioned Wi-Fi record approach. Verify storage
  failure and interrupted writes do not produce a false saved confirmation
  or a mixture of old and new settings after reboot.
- [ ] **P2 — Make slideshow order chronological:** The image and video
  selection functions in `SDCard.cpp` compare filenames, but current
  filenames contain content hashes rather than creation dates. Persist a
  saved timestamp or sequence number, define ordering for older files, and
  use it for newest-first/oldest-first playback. Verify order survives reboot
  and does not depend on alphabetical hash order.
- [ ] **P2 — Select the board through one build choice:**
  `FirmwareTarget.h` currently explicitly selects Cheap Yellow Display
  before the automatic-selection block. Make the build command/profile
  select the target without editing shared source. Keep clear mismatch
  errors and distinguish the two ESP32-S3 displays. The user compiles each
  target manually; verify the resulting board identity and package manifest.
- [ ] **P2 — Make timers safe across uptime rollover:** Replace absolute
  `millis()` deadline comparisons in the main loop, SD remount checks, and
  JPEG download timeout with rollover-safe elapsed-time comparisons. Add
  focused tests around the approximately 50-day counter wrap, including a
  deadline missed while another operation runs, so retries, polling,
  slideshow timing, and downloads cannot stall or time out incorrectly.

### Hardware validation

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
  Manually compile/flash 1.1.6 on all four targets. Test power cuts before/during
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
