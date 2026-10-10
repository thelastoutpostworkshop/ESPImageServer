import test from 'node:test'
import assert from 'node:assert/strict'
import { access } from 'node:fs/promises'
import { boardThumbnailSource } from '../src/boardThumbnail.js'

test('known board targets use existing local catalog assets', async () => {
  for (const target of ['JC4827W543', 'ST7701_320X820', 'ESP32_C6_LCD_147', 'CHEAP_YELLOW_DISPLAY', 'ESP32_S3_AMOLED_143']) {
    const source = boardThumbnailSource(target)
    assert.equal(source, `/ui/board-catalog/${target}.png`)
    await access(new URL(`../public/board-catalog/${target}.png`, import.meta.url))
  }
})

test('compiled target prefixes select the same board without changing target spelling', () => {
  assert.equal(boardThumbnailSource('FIRMWARE_TARGET_ESP32_C6_LCD_147'), boardThumbnailSource('ESP32_C6_LCD_147'))
  assert.equal(boardThumbnailSource('firmware_target_ESP32_C6_LCD_147'), null)
  assert.equal(boardThumbnailSource('FIRMWARE_TARGET_esp32_c6_lcd_147'), null)
})

test('unknown and legacy identities never infer a board or construct an arbitrary asset path', () => {
  for (const value of [null, undefined, '', 'legacy', 'ESP32', 'Waveshare ESP32-C6 LCD 1.47', '172x320',
    '../JC4827W543', 'FIRMWARE_TARGET_UNKNOWN', { name: 'JC4827W543', width: 480, height: 272 }]) {
    assert.equal(boardThumbnailSource(value), null)
  }
})
