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
    savedVideoFps: () => 15, onDisplaySdCardLabel: { value: 'On display SD card' },
  })
  vm.runInContext(statusFunctions + presenceFunctions, context)
  return context
}

for (const type of ['image', 'video']) {
  const creation = type === 'image' ? { sd_card_content_keys: ['v1-imagehash'] } : { id: 'videoid' }
  const key = type === 'image' ? 'v1-imagehash' : 'v1-videoid-320x820-fps15'
  const file = { name: `esp-${type}-20260912-131013-${key}.${type === 'image' ? 'jpg' : 'mjpeg'}`, content_key: key, type }

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
  const ui = gallery([{ name: 'saved.jpg', type: 'image', content_key: 'new-key', verified: true }])
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
