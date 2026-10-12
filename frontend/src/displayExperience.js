const rotations = new Set([0, 90, 180, 270])

export function displayExperienceDefaults() {
  return {
    current_mode: 'server_controlled',
    offline_experience: 'slideshow',
    slideshow_interval_ms: 15000,
    slideshow_order: 'newest_first',
    orientation_filter_enabled: false,
    orientation_rotation: 0,
  }
}

export function normalizeDisplayExperience(value = {}) {
  return {
    ...displayExperienceDefaults(), ...value,
    orientation_filter_enabled: value.orientation_filter_enabled === true,
    orientation_rotation: rotations.has(value.orientation_rotation) ? value.orientation_rotation : 0,
  }
}

export function displayExperienceSettings(value, intervalSeconds) {
  return {
    offline_experience: value.offline_experience,
    slideshow_interval_ms: Math.round(Number(intervalSeconds) * 1000),
    slideshow_order: value.slideshow_order,
    orientation_filter_enabled: value.orientation_filter_enabled === true,
    orientation_rotation: rotations.has(value.orientation_rotation) ? value.orientation_rotation : 0,
  }
}

export function experienceMediaCounts(files, experience) {
  const video = experience.offline_experience === 'video_loop'
  const media = (Array.isArray(files) ? files : []).filter(file =>
    file.type ? file.type === (video ? 'video' : 'image') : file.name?.endsWith(video ? '.mjpeg' : '.jpg'))
  const unknown = media.filter(file => !rotations.has(file.orientation_rotation)).length
  return {
    total: media.length,
    unknown,
    matching: experience.orientation_filter_enabled
      ? media.filter(file => rotations.has(file.orientation_rotation) && file.orientation_rotation === experience.orientation_rotation).length
      : media.length,
  }
}

export function experienceOrientationGeometry(display, rotation) {
  const width = Number(display?.width) > 0 ? Number(display.width) : 4
  const height = Number(display?.height) > 0 ? Number(display.height) : 3
  rotation = rotations.has(rotation) ? rotation : 0
  const sideways = rotation === 90 || rotation === 270
  const scale = 196 / Math.max(width, height)
  const nativeWidth = width * scale
  const nativeHeight = height * scale
  const target = display?.board_target?.replace(/^FIRMWARE_TARGET_/, '')
  const round = target === 'ESP32_S3_AMOLED_143'
  return {
    rotation,
    round,
    nativeWidth, nativeHeight,
    width: sideways ? height : width,
    height: sideways ? width : height,
    artworkWidth: sideways ? nativeHeight : nativeWidth,
    artworkHeight: sideways ? nativeWidth : nativeHeight,
    shape: round ? 'Round' : width === height ? 'Square' : (sideways ? height > width : width > height) ? 'Landscape' : 'Portrait',
    // Match the generation preview: turn the board opposite to the artwork.
    boardRotation: -rotation,
  }
}
