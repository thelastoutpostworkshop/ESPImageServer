# TODO

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


## Browser UX review — 2026-09-06

Reviewed the running app reporting v1.0.62 at `http://127.0.0.1:8000`,
including desktop and 390×844 phone layouts. These are observed behavior and
design follow-ups; implementation causes have not been verified.


3. **P2 — Make desktop Creation Library filters readable.** With the library
   pinned at its observed width, all three filter labels were truncated to
   “Filt…”. Use short labels such as **Model**, **Display**, and **On SD card**,
   or stack filters when the pane is narrow. Keep the active display context
   available without putting its full name inside every narrow field. Check
   selected values and clear controls at desktop and phone widths.


## Platform delivery - remaining work

Prioritize the Windows x64 and Ubuntu 24.04 x64 release. macOS release delivery
is deferred. Keep the no-CPU-generation policy and preserve Windows behavior.

### Windows verification

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
### Release and updates

- [ ] **P2 - Finish native distribution and update flows:** Complete native
  icons, signing/notarization, historical settings-schema migration, and
  automatic updates. Preserve settings and user creations. Keep pyproject.toml
  as the version source and publish per-platform checksums. macOS release
  delivery remains deferred; Windows code signing is tracked under Backend and
  installer hardening.
- [ ] **P1 - Finish Windows and Linux release:** Release collection now includes
  only the Windows x64 .exe and Ubuntu 24.04 x64 .deb with their checksums.
  macOS release delivery is deferred while its CI coverage remains. Run the
  tag-triggered draft workflow for a matching v<version> tag, review its downloads and
  user-facing release notes, then publish when ready. Existing drafts are not
  modified by these source changes; use an unused version for a fresh draft.
  Tag-trigger validation passes locally; confirm the first hosted tag run.
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
