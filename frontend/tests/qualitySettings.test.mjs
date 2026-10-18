import test from 'node:test'
import assert from 'node:assert/strict'
import {
  imageQualityLevel,
  videoQualityLevel,
  imageQualityFromLevel,
  videoQualityFromLevel,
} from '../src/qualitySettings.js'

test('both sliders go from lowest to highest quality at the same endpoints', () => {
  assert.equal(imageQualityFromLevel(1), 40)
  assert.equal(imageQualityFromLevel(10), 100)
  assert.equal(videoQualityFromLevel(1), 20)
  assert.equal(videoQualityFromLevel(10), 2)
  assert.equal(imageQualityLevel(40), 1)
  assert.equal(imageQualityLevel(100), 10)
  assert.equal(videoQualityLevel(20), 1)
  assert.equal(videoQualityLevel(2), 10)
})

test('all ten integer levels remain distinct and increase encoder quality', () => {
  let previousImage = 0
  let previousVideo = Infinity
  for (let level = 1; level <= 10; level += 1) {
    const image = imageQualityFromLevel(level)
    const video = videoQualityFromLevel(level)
    assert.ok(Number.isInteger(image))
    assert.ok(Number.isInteger(video))
    assert.ok(image > previousImage, 'Higher image level must improve quality')
    assert.ok(video < previousVideo, 'Higher video level must reduce compression')
    assert.equal(imageQualityLevel(image), level)
    assert.equal(videoQualityLevel(video), level)
    previousImage = image
    previousVideo = video
  }
})

test('legacy settings display the nearest available level without changing their values', () => {
  const settings = Object.freeze({ jpeg_quality: 85, video_jpeg_quality: 11 })
  assert.equal(imageQualityLevel(settings.jpeg_quality), 8)
  assert.equal(videoQualityLevel(settings.video_jpeg_quality), 6)
  assert.deepEqual(settings, { jpeg_quality: 85, video_jpeg_quality: 11 })
  // The API supports a wider range than the UI. Keep those values until edited.
  const olderSettings = Object.freeze({ jpeg_quality: 1, video_jpeg_quality: 31 })
  assert.equal(imageQualityLevel(olderSettings.jpeg_quality), 1)
  assert.equal(videoQualityLevel(olderSettings.video_jpeg_quality), 1)
  assert.deepEqual(olderSettings, { jpeg_quality: 1, video_jpeg_quality: 31 })
})

test('presentation stays monotonic across the full persisted encoder ranges', () => {
  let previousImageLevel = 1
  for (let quality = 1; quality <= 100; quality += 1) {
    const level = imageQualityLevel(quality)
    assert.ok(level >= previousImageLevel && level <= 10)
    previousImageLevel = level
  }
  let previousVideoLevel = 10
  for (let quality = 2; quality <= 31; quality += 1) {
    const level = videoQualityLevel(quality)
    assert.ok(level <= previousVideoLevel && level >= 1)
    previousVideoLevel = level
  }
})

test('out-of-range finite values clamp and fractional slider input snaps to an integer level', () => {
  assert.equal(imageQualityLevel(-100), 1)
  assert.equal(imageQualityLevel(200), 10)
  assert.equal(videoQualityLevel(-100), 10)
  assert.equal(videoQualityLevel(200), 1)
  for (const [convert, low, high] of [
    [imageQualityFromLevel, 40, 100],
    [videoQualityFromLevel, 20, 2],
  ]) {
    assert.equal(convert(-10), low)
    assert.equal(convert(100), high)
    assert.equal(convert(4.2), convert(4))
    assert.equal(convert(4.8), convert(5))
  }
})

test('invalid input uses safe encoder defaults instead of producing NaN', () => {
  for (const invalid of [undefined, null, NaN, Infinity, -Infinity, '', '10', {}, []]) {
    assert.equal(imageQualityLevel(invalid), imageQualityLevel(85))
    assert.equal(videoQualityLevel(invalid), videoQualityLevel(10))
    assert.equal(imageQualityFromLevel(invalid), 85)
    assert.equal(videoQualityFromLevel(invalid), 10)
  }
})
