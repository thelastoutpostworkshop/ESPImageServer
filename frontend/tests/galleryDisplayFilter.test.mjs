import test from 'node:test'
import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import vm from 'node:vm'
import { computed, effectScope, nextTick, ref, watch } from 'vue'
import { boardThumbnailSource } from '../src/boardThumbnail.js'

const source = await readFile(new URL('../src/App.vue', import.meta.url), 'utf8')
function production(start, end) {
  const from = source.indexOf(start), to = source.indexOf(end, from + start.length)
  assert.ok(from >= 0 && to > from, `Missing production boundary: ${start} / ${end}`)
  return source.slice(from, to)
}

const displayCode = production('const selectedRegisteredDisplay = computed(', 'const hasDisplayTargets = computed(')
const nameCode = production('function creationModelName(', 'const creationSdCardInventoryConfirmed = computed(')
const filterCode = production('function matchesCreationFilters(', 'const filteredGalleryItems = computed(')
const waveshare = { id: 'waveshare', name: 'Waveshare 3.16', board_target: 'ST7701_320X820', online: true }
const c6 = { id: 'c6', name: 'C6 screen', board_target: 'ESP32_C6_LCD_147', online: false }
const creation = (id, name, extraMetadata = {}) => ({
  id, metadata: { ...(name ? { display: { name } } : {}), ...extraMetadata },
})

// Execute the real option computation, filter, and watcher with Vue refs.
// No server, display command, storage, or hardware actions are involved.
function setup(t, options = {}) {
  const ui = vm.createContext({
    computed, watch,
    displays: ref(options.displays || [waveshare, c6]),
    activeDisplayId: ref(options.activeDisplayId ?? 'waveshare'),
    legacyDisplay: ref(options.legacyDisplay || null),
    savedImages: ref(options.images || []),
    savedVideos: ref(options.videos || []),
    creationDisplayFilter: ref(null),
    creationModelFilter: ref(null),
    creationSdCardFilter: ref(null),
    creationIsOnDisplaySdCard: () => false,
  })
  const scope = effectScope()
  scope.run(() => vm.runInContext(`${displayCode}\n${nameCode}\n${filterCode}\n
    globalThis.view = { display, creationDisplayOptions, filteredSavedImages, filteredSavedVideos };
  `, ui))
  t.after(() => scope.stop())
  return ui
}

const optionsFor = ui => Array.from(ui.view.creationDisplayOptions.value)
const optionFor = (ui, value) => optionsFor(ui).find(option => option.value === value)
const filteredIds = (ui, type) => Array.from(ui.view[`filteredSaved${type}`].value, item => item.id)

test('the active Waveshare board is selectable and selected before any creations exist', t => {
  const ui = setup(t)
  assert.equal(ui.creationDisplayFilter.value, waveshare.name)
  assert.equal(optionFor(ui, waveshare.name).boardTarget, waveshare.board_target)
  assert.equal(boardThumbnailSource(optionFor(ui, waveshare.name).boardTarget), '/ui/board-catalog/ST7701_320X820.png')
  assert.ok(optionFor(ui, c6.name), 'Offline registered boards remain selectable')
  assert.deepEqual(filteredIds(ui, 'Images'), [])
  assert.deepEqual(filteredIds(ui, 'Videos'), [])
})

test('registered, legacy, and historical display names form one deduplicated option list', t => {
  const ui = setup(t, {
    activeDisplayId: '', legacyDisplay: { connected: true, name: 'Legacy screen' },
    images: [creation('old-image', 'Retired screen'), creation('same-name', waveshare.name)],
    videos: [creation('old-video', 'Retired screen'), creation('other-video', 'Another retired screen'), creation('unrecorded-video', '')],
  })
  const values = optionsFor(ui).map(option => option.value)
  for (const name of [waveshare.name, c6.name, 'Legacy screen', 'Retired screen', 'Another retired screen', '__no_display__']) {
    assert.ok(values.includes(name), `Missing display option: ${name}`)
  }
  assert.equal(values.length, new Set(values).size)
  assert.equal(ui.creationDisplayFilter.value, 'Legacy screen')
  assert.equal(optionFor(ui, '__no_display__').title, 'No display recorded')
})

test('historical metadata resolves its photo through a stable display ID after a rename', t => {
  const ui = setup(t, {
    displays: [{ ...waveshare, name: 'Renamed screen' }],
    images: [creation('old-image', 'Original screen name', { display_id: waveshare.id })],
    videos: [creation('old-video', 'Original video name', { display_ids: [waveshare.id] })],
  })
  assert.equal(optionFor(ui, 'Original screen name').boardTarget, waveshare.board_target)
  assert.equal(optionFor(ui, 'Original video name').boardTarget, waveshare.board_target)
  assert.ok(optionFor(ui, 'Renamed screen'))
})

test('ambiguous and unknown historical boards retain a generic thumbnail', t => {
  const ui = setup(t, {
    displays: [{ ...waveshare, name: 'Shared name' }, { ...c6, name: 'Shared name' }],
    images: [creation('legacy', 'Unknown board', { display: { name: 'Unknown board', width: 172, height: 320 } })],
  })
  assert.equal(optionsFor(ui).filter(option => option.value === 'Shared name').length, 1)
  assert.equal(boardThumbnailSource(optionFor(ui, 'Shared name').boardTarget), null)
  assert.equal(boardThumbnailSource(optionFor(ui, 'Unknown board').boardTarget), null)
})

test('a matching name without an authoritative historical target cannot guess a photo', t => {
  const ui = setup(t, { images: [creation('old-image', waveshare.name)] })
  assert.equal(boardThumbnailSource(optionFor(ui, waveshare.name).boardTarget), null)
})

test('a remembered active ID selects its display once the initial registry result arrives', async t => {
  const ui = setup(t, { displays: [], activeDisplayId: waveshare.id, images: [creation('old-image', 'Retired screen')] })
  assert.equal(ui.creationDisplayFilter.value, null)
  assert.equal(optionFor(ui, waveshare.name), undefined)
  ui.displays.value = [{ ...waveshare }]
  await nextTick()
  assert.equal(ui.creationDisplayFilter.value, waveshare.name)
  assert.ok(optionFor(ui, waveshare.name))
})

test('changing the active identity or its name follows that display and removal clears the filter', async t => {
  const ui = setup(t, { images: [creation('old-image', 'Retired screen')] })
  ui.creationDisplayFilter.value = 'Retired screen'
  ui.activeDisplayId.value = c6.id
  await nextTick()
  assert.equal(ui.creationDisplayFilter.value, c6.name)
  ui.displays.value = ui.displays.value.map(target => target.id === c6.id ? { ...target, name: 'Renamed C6' } : { ...target })
  await nextTick()
  assert.equal(ui.creationDisplayFilter.value, 'Renamed C6')
  ui.displays.value = [{ ...waveshare }]
  await nextTick()
  assert.equal(ui.creationDisplayFilter.value, null)
})

for (const [selection, expectedImages, expectedVideos] of [
  [null, ['retired-image', 'current-image'], ['unrecorded-video']],
  ['Retired screen', ['retired-image'], []],
  ['__no_display__', [], ['unrecorded-video']],
]) {
  test(`background registry and gallery updates preserve manual filter ${JSON.stringify(selection)}`, async t => {
    const ui = setup(t, {
      images: [creation('retired-image', 'Retired screen'), creation('current-image', waveshare.name)],
      videos: [creation('unrecorded-video', '')],
    })
    ui.creationDisplayFilter.value = selection
    for (const online of [false, true]) {
      ui.displays.value = ui.displays.value.map(target => ({ ...target, online, last_seen: online ? 'new contact' : 'old contact' }))
      ui.savedImages.value = ui.savedImages.value.map(item => ({ ...item }))
      ui.savedVideos.value = ui.savedVideos.value.map(item => ({ ...item }))
      await nextTick()
      assert.equal(ui.creationDisplayFilter.value, selection)
      assert.deepEqual(filteredIds(ui, 'Images'), expectedImages)
      assert.deepEqual(filteredIds(ui, 'Videos'), expectedVideos)
    }
  })
}

test('the active-display default filters both saved images and videos and clearing shows every display', t => {
  const ui = setup(t, {
    images: [creation('current-image', waveshare.name), creation('other-image', c6.name)],
    videos: [creation('current-video', waveshare.name), creation('other-video', 'Retired screen')],
  })
  assert.deepEqual(filteredIds(ui, 'Images'), ['current-image'])
  assert.deepEqual(filteredIds(ui, 'Videos'), ['current-video'])
  ui.creationDisplayFilter.value = null
  assert.deepEqual(filteredIds(ui, 'Images'), ['current-image', 'other-image'])
  assert.deepEqual(filteredIds(ui, 'Videos'), ['current-video', 'other-video'])
})
