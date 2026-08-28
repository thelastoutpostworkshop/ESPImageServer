# TODO

## Mobile frontend review

1. **P2 — Add a mobile visual/regression test pass.** Check at 390×844
   portrait, 844×390 landscape, and a notched iPhone Safari view. Cover
   opening and closing the Creation Library, navigation, long display names,
   and the Queue, Diagnostics, and result-action layouts.

## Changes in the UI
2. When an error occur, the ui should not change to the diagnostics page automatically
3. Saving to an sd card and looking at the sd card, created date is "Unknown"
4. In Display SD card, the user should be able to select multiple files for deletion
5. When saving to an sd card, does the image is saved on the currently selected display ?
6. the job queue list should be from the most recent to the oldest

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
