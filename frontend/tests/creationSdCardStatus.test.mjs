import test from 'node:test'
import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import vm from 'node:vm'

const source = await readFile(new URL('../src/App.vue', import.meta.url), 'utf8')
const statusFunctions = source.slice(source.indexOf('function creationSdCardStatus('), source.indexOf('const savedMetadataLabels'))
const presenceFunctions = source.slice(source.indexOf('function creationIsOnDisplaySdCard('), source.indexOf('function matchesCreationFilters('))

function gallery(files, overrides = {}) {
  const report = { available: true, verified_saves: true, files, ...overrides }
  const context = vm.createContext({
    displaySdCard: { value: report }, displaySdCardFiles: () => report.files,
    creationSdCardInventoryConfirmed: { value: true },
    savedImages: { value: [] },
    display: { value: { connected: true, width: 320, height: 820 } },
    displayRotation: { value: 0 },
    savedVideoFps: () => 15, onDisplaySdCardLabel: { value: 'On display SD card' },
  })
  vm.runInContext(statusFunctions + presenceFunctions, context)
  return context
}

for (const type of ['image', 'video']) {
  const creation = type === 'image' ? { sd_card_content_keys: ['v1-imagehash'] } : { id: 'videoid', metadata: { rotation: 0 } }
  const key = type === 'image' ? 'v1-imagehash' : 'v1-videoid-320x820-fps15'
  const file = { name: `esp-${type}-20260912-131013-r0-${key}.${type === 'image' ? 'jpg' : 'mjpeg'}`, content_key: key, type, orientation_rotation: 0 }

  test(`${type}: unverified files remain visible, with Save available`, () => {
    const ui = gallery([{ ...file, verified: false }])
    assert.equal(ui.creationIsOnDisplaySdCard(creation, type), true)
    assert.equal(ui.creationIsSavedForCurrentDisplay(creation, type), false)
    assert.match(ui.creationSdCardLabel(creation, type), /save not verified/)
    assert.equal(ui.creationSdCardColor(creation, type), 'warning')
  })

  test(`${type}: verified saves still disable redundant saves`, () => {
    const ui = gallery([{ ...file, verified: false }, { ...file, verified: true }])
    assert.equal(ui.creationIsSavedForCurrentDisplay(creation, type), true)
    assert.doesNotMatch(ui.creationSdCardLabel(creation, type), /not verified/)
    assert.equal(ui.creationSdCardColor(creation, type), 'success')
  })

  test(`${type}: absent card/files are not marked present`, () => {
    assert.equal(gallery([]).creationIsOnDisplaySdCard(creation, type), false)
    assert.equal(gallery([file], { available: false }).creationIsOnDisplaySdCard(creation, type), false)
  })

  test(`${type}: reports without verification cannot disable Save`, () => {
    assert.equal(gallery([file], { verified_saves: false }).creationIsSavedForCurrentDisplay(creation, type), false)
  })
}

test('legacy filenames without current content keys are not matched', () => {
  const ui = gallery([
    { name: 'esp-image-imagehash.jpg', type: 'image', verified: true },
    { name: 'esp-video-videoid-fps15.mjpeg', type: 'video', verified: true },
  ])
  assert.equal(ui.creationIsOnDisplaySdCard({ sd_card_content_keys: ['v1-imagehash'] }, 'image'), false)
  assert.equal(ui.creationIsOnDisplaySdCard({ id: 'videoid' }, 'video'), false)
})

test('an open image menu uses refreshed keys for its existing image ID', () => {
  const staleMenuImage = { id: 'saved-image', sd_card_content_keys: ['old-key'] }
  const ui = gallery([{ name: 'saved.jpg', type: 'image', content_key: 'new-key', verified: true, orientation_rotation: 0 }])
  assert.equal(ui.creationIsSavedForCurrentDisplay(staleMenuImage, 'image'), false)
  ui.savedImages.value = [{ id: 'saved-image', sd_card_content_keys: ['new-key'] }]
  assert.equal(ui.creationIsOnDisplaySdCard(staleMenuImage, 'image'), true)
  assert.equal(ui.creationIsSavedForCurrentDisplay(staleMenuImage, 'image'), true)
})

test('refreshed image keys replace stale matches rather than merging them', () => {
  const staleImage = { id: 'saved-image', sd_card_content_keys: ['old-key'] }
  const ui = gallery([{ name: 'old.jpg', type: 'image', content_key: 'old-key', verified: true }])
  ui.savedImages.value = [{ id: 'saved-image', sd_card_content_key: 'new-key' }]
  assert.equal(ui.creationIsOnDisplaySdCard(staleImage, 'image'), false)
  assert.equal(ui.creationIsSavedForCurrentDisplay(staleImage, 'image'), false)
})

test('an image in another orientation remains present but permits saving the selected rotation', () => {
  const creation = { sd_card_content_keys: ['v1-pattern'] }
  const other = { name: 'pattern-r90.jpg', type: 'image', content_key: 'v1-pattern', verified: true, orientation_rotation: 90 }
  const ui = gallery([other])
  assert.equal(ui.creationIsOnDisplaySdCard(creation, 'image'), true)
  assert.equal(ui.creationIsSavedForCurrentDisplay(creation, 'image'), false)
  assert.match(ui.creationSdCardLabel(creation, 'image'), /another orientation/)
  ui.displayRotation.value = 90
  assert.equal(ui.creationIsSavedForCurrentDisplay(creation, 'image'), true)
  ui.displayRotation.value = 270
  assert.equal(ui.creationIsSavedForCurrentDisplay(creation, 'image'), false)
})

test('a matching image rendition takes priority over a verified copy at a different angle', () => {
  const creation = { sd_card_content_keys: ['v1-pattern'] }
  const files = [
    { name: 'other.jpg', type: 'image', content_key: 'v1-pattern', verified: true, orientation_rotation: 90 },
    { name: 'matching.jpg', type: 'image', content_key: 'v1-pattern', verified: true, orientation_rotation: 0 },
  ]
  const ui = gallery(files)
  assert.equal(ui.creationSdCardStatus(creation, 'image').file.name, 'matching.jpg')
  assert.equal(ui.creationIsSavedForCurrentDisplay(creation, 'image'), true)
})

test('video save availability uses its recorded rotation instead of the current image rotation', () => {
  const creation = { id: 'videoid', metadata: { rotation: 270 } }
  const ui = gallery([{ name: 'movie.mjpeg', type: 'video', content_key: 'v1-videoid-320x820-fps15', verified: true, orientation_rotation: 90 }])
  assert.equal(ui.creationIsOnDisplaySdCard(creation, 'video'), true)
  assert.equal(ui.creationIsSavedForCurrentDisplay(creation, 'video'), false)
  ui.displaySdCard.value.files[0].orientation_rotation = 270
  assert.equal(ui.creationIsSavedForCurrentDisplay(creation, 'video'), true)
})
