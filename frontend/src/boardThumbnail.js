const boardTargets = new Set([
  'JC4827W543',
  'ST7701_320X820',
  'ESP32_C6_LCD_147',
  'CHEAP_YELLOW_DISPLAY',
  'ESP32_S3_AMOLED_143',
])

export function boardThumbnailSource(boardTarget) {
  if (typeof boardTarget !== 'string') return null
  const target = boardTarget.startsWith('FIRMWARE_TARGET_')
    ? boardTarget.slice('FIRMWARE_TARGET_'.length)
    : boardTarget
  return boardTargets.has(target) ? `/ui/board-catalog/${target}.png` : null
}
