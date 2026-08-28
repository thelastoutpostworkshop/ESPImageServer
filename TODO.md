# TODO

## Mobile frontend review

1. **P2 — Add a mobile visual/regression test pass.** Check at 390×844
   portrait, 844×390 landscape, and a notched iPhone Safari view. Cover
   opening and closing the Creation Library, navigation, long display names,
   and the Queue, Diagnostics, and result-action layouts.

## Multi-display support

Replace the current single active-display model with a persistent,
device-targeted display registry. Do not enable multiple displays by merely
accepting more `/display` announcements: the last board would still control
the shared dimensions, rotation, JPEG, SD-card report, and command queue.

1. **P1 — Introduce persistent MAC display identities.** **Complete:** every
   display now has a stable eFuse-MAC hardware ID, editable friendly name,
   persistent profile, per-device rotation, and last-seen status in the local
   SQLite registry. Firmware client work remains in item 7; never use the
   friendly name as identity.

2. **P1 — Replace global display endpoints and state with display-scoped
   equivalents.** **Complete for the server foundation:** MAC registration,
   list/detail, MAC-identified heartbeat, and per-device settings routes now
   live under `/displays`. Target-specific `/latest.jpg` delivery is part of
   item 3. Keep the legacy single-display API only as a temporary compatibility
   layer while firmware is upgraded.

3. **P1 — Deliver target-specific image renditions.** **Complete in source:**
   retain a master creation, then lazily produce and cache a JPEG for each
   display's native dimensions, rotation, and JPEG quality. Each ETag includes
   the artwork revision and target settings. Generation and saved-image actions
   accept optional target display IDs; each assignment also retains its chosen
   crop or fit treatment so an ESP32 always receives its native JPEG.

4. **P1 — Make display commands and SD-card state per device.** **Complete:**
   commands, acknowledgements, SD-card reports, experience settings,
   deduplication, and thumbnail paths are now display-ID scoped. A command
   retrieved or acknowledged by one board cannot affect another board.

5. **P2 — Add multi-display targeting to the web app.** **Complete:** the
   image generator shows registered screens with connection status, dimensions,
   firmware, and last-seen time. A persistent app-bar selector chooses one
   active display for generation, saved-image actions, rotation, SD-card
   management, and offline-experience settings at a time.

6. **P2 — Define the broadcast-aspect policy.** **Complete:** mixed-shape
   target selections require an explicit choice: center-crop one composition,
   fit one composition with black borders, or generate separate compositions
   for each aspect-ratio group. Existing Creation Gallery images support crop
   and fit; separate artwork is intentionally limited to new generation. The
   web app deliberately selects one active display at a time, while the API
   retains this policy for automation and future advanced workflows.

7. **P1 — Update the ESP32 firmware API client.** Automatically register each
   board's stable eFuse MAC address, then use its MAC-identified scoped routes
   for latest-image polling, command polling, acknowledgements, and SD-card
   reports. Preserve the device-specific ETag across polls. The MAC is an
   identifier, not a password, so this design is for a trusted home LAN. Do
   not build firmware as part of the server task; the firmware repository is
   upgraded and flashed separately. **Complete in source:** a manually flashed
   1.1.0 board automatically registers with its MAC address. Per-display image
   renditions remain item 3.

8. **P1 — Test and stage the migration.** Cover device isolation, per-display
   rotations and resolutions, independent ETags, broadcasts, offline boards,
   command/report isolation, restart persistence, and legacy-client behavior.
   Release server compatibility support first, upgrade every board, then expose
   multi-display mode and eventually remove the legacy routes.

The existing single GPU image/video generation worker remains shared. Fan-out
and JPEG resizing run after generation and must not permit concurrent image and
video model use.

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
