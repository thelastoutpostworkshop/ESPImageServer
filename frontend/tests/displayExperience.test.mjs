import test from 'node:test'
import assert from 'node:assert/strict'
import { displayExperienceDefaults, normalizeDisplayExperience, displayExperienceSettings, experienceMediaCounts, experienceOrientationGeometry } from '../src/displayExperience.js'

test('orientation filtering starts off and saved choices round-trip into preview and save requests', () => {
  const fresh = displayExperienceDefaults()
  assert.equal(fresh.orientation_filter_enabled, false)
  assert.equal(fresh.orientation_rotation, 0)
  const chosen = { ...fresh, offline_experience: 'video_loop', orientation_filter_enabled: true, orientation_rotation: 270 }
  const settings = displayExperienceSettings(chosen, 1.5)
  assert.deepEqual(settings, {
    offline_experience: 'video_loop', slideshow_interval_ms: 1500, slideshow_order: 'newest_first',
    orientation_filter_enabled: true, orientation_rotation: 270,
  })
  const restored = normalizeDisplayExperience(settings)
  assert.deepEqual(displayExperienceSettings(restored, 1.5), settings)
  assert.equal(displayExperienceDefaults().orientation_filter_enabled, false)
})

test('exact orientation matching separates 90 from 270 and never counts unknown metadata as zero', () => {
  const files = [
    { name: 'one.jpg', type: 'image', orientation_rotation: 90 },
    { name: 'two.jpg', type: 'image', orientation_rotation: 270 },
    { name: 'three.jpg', type: 'image', orientation_rotation: 0 },
    { name: 'four.jpg', type: 'image', orientation_rotation: null },
    { name: 'five.jpg', type: 'image' },
    { name: 'six.jpg', type: 'image', orientation_rotation: false },
    { name: 'one.mjpeg', type: 'video', orientation_rotation: 90 },
  ]
  const settings = { ...displayExperienceDefaults(), orientation_filter_enabled: true, orientation_rotation: 90 }
  assert.deepEqual(experienceMediaCounts(files, settings), { total: 6, unknown: 3, matching: 1 })
  settings.orientation_rotation = 0
  assert.equal(experienceMediaCounts(files, settings).matching, 1)
  settings.orientation_filter_enabled = false
  assert.equal(experienceMediaCounts(files, settings).matching, 6)
  settings.offline_experience = 'video_loop'
  settings.orientation_filter_enabled = true
  assert.deepEqual(experienceMediaCounts(files, settings), { total: 1, unknown: 0, matching: 0 })
})

test('preview uses each active board native dimensions and distinguishes all four physical rotations', () => {
  const boards = [
    { board_target: 'JC4827W543', width: 480, height: 272 },
    { board_target: 'ST7701_320X820', width: 320, height: 820 },
    { board_target: 'ESP32_C6_LCD_147', width: 172, height: 320 },
    { board_target: 'CHEAP_YELLOW_DISPLAY', width: 240, height: 320 },
    { board_target: 'ESP32_S3_AMOLED_143', width: 466, height: 466 },
  ]
  for (const board of boards) {
    for (const rotation of [0, 90, 180, 270]) {
      const preview = experienceOrientationGeometry(board, rotation)
      const sideways = rotation === 90 || rotation === 270
      assert.equal(preview.width, sideways ? board.height : board.width)
      assert.equal(preview.height, sideways ? board.width : board.height)
      assert.equal(preview.boardRotation, -rotation)
      assert.ok(Math.abs(preview.nativeWidth / preview.nativeHeight - board.width / board.height) < 1e-12)
      assert.ok(Math.max(preview.artworkWidth, preview.artworkHeight) <= 196 + 1e-12)
      assert.equal(preview.round, board.board_target === 'ESP32_S3_AMOLED_143')
      if (preview.round) assert.equal(preview.shape, 'Round')
    }
  }
})
