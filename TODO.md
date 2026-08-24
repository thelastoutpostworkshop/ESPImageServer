# TODO

## Improve frontend UX

- Make browsing the Creation Library non-destructive: selecting a saved image
  should preview it without replacing the current generator draft or sending it
  to the connected display. Provide explicit **Use settings** and **Show on
  display** actions instead.
- Add a visible per-creation **More actions** control (or a selected-item action
  bar). Key actions are currently hidden behind right-click context menus, which
  is difficult to discover and does not work well on touch screens.
- Make the Creation Library view toggle consistent: list view should include
  saved videos, or the control should clearly say that it changes image view
  only.
- Confirm before deleting a display SD-card file, including the file name and
  media type in the confirmation. Reuse the gallery's deletion-confirmation
  pattern where appropriate.
- Make the Creation Library easier to find by adding it to the primary
  navigation or showing a labeled control on wider screens instead of relying
  only on the app-bar icon.
- Replace the video frame-count constraint with duration presets that calculate
  valid frame counts from the selected frame rate; keep raw frames as an
  advanced control if needed.
- Clarify that **Save to display SD card** stores content for offline playback;
  pair it with a separate, explicit **Show on display** action.

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
