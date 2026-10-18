const IMAGE_DEFAULT = 85
const VIDEO_DEFAULT = 10

function finiteOr(value, fallback) {
  return typeof value === 'number' && Number.isFinite(value) ? value : fallback
}

function clamp(value, min, max) {
  return Math.min(max, Math.max(min, value))
}

function sliderLevel(value) {
  return Math.round(clamp(value, 1, 10))
}

// Both sliders use levels 1–10, increasing from smaller files to higher quality.
// Levels are approximate for legacy encoder values. Read these for presentation
// only; convert back to encoder values only when the user changes a slider.
export function imageQualityLevel(quality) {
  const raw = clamp(finiteOr(quality, IMAGE_DEFAULT), 40, 100)
  return sliderLevel(1 + (raw - 40) * 9 / 60)
}

export function videoQualityLevel(quality) {
  const raw = clamp(finiteOr(quality, VIDEO_DEFAULT), 2, 20)
  return sliderLevel(1 + (20 - raw) / 2)
}

export function imageQualityFromLevel(level) {
  if (typeof level !== 'number' || !Number.isFinite(level)) return IMAGE_DEFAULT
  return Math.round(40 + (sliderLevel(level) - 1) * 60 / 9)
}

export function videoQualityFromLevel(level) {
  if (typeof level !== 'number' || !Number.isFinite(level)) return VIDEO_DEFAULT
  return 20 - (sliderLevel(level) - 1) * 2
}
