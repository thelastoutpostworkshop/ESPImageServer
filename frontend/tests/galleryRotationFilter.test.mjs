import test from 'node:test'
import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import vm from 'node:vm'
import { computed, effectScope, nextTick, ref, watch } from 'vue'
import { filterGallerySelection, gallerySelectionKey } from '../src/galleryBulkSave.js'

const source = await readFile(new URL('../src/App.vue', import.meta.url), 'utf8')
function production(start, end) {
  const from = source.indexOf(start), to = source.indexOf(end, from + start.length)
  assert.ok(from >= 0 && to > from, `Missing production boundary: ${start} / ${end}`)
  return source.slice(from, to)
}

const stateCode = production('const creationModelFilter = ref(', 'const exportingAllPrompts = ref(')
const nameCode = production('function creationModelName(', 'const creationSdCardInventoryConfirmed = computed(')
const filterCode = production('function matchesCreationFilters(', 'const creationModelOptions = computed(')
const listCode = production('const filteredSavedImages = computed(', 'const selectedGalleryCreations = computed(')
const selectionCode = production('watch(filteredGalleryItems, items => {', 'function galleryCreationSelected(')
const creation = (id, rotation, extraMetadata = {}) => ({ id, metadata: { rotation, ...extraMetadata } })

// Run the production filter, computed lists, and selection watcher with Vue refs.
function setup(t, { images = [], videos = [], onSdCard = [] } = {}) {
  const onSdCardKeys = new Set(onSdCard.map(gallerySelectionKey))
  const ui = vm.createContext({
    computed, ref, watch, filterGallerySelection,
    savedImages: ref(images), savedVideos: ref(videos), selectedCreationKeys: ref([]),
    creationIsOnDisplaySdCard: (item, type) => onSdCardKeys.has(gallerySelectionKey({ id: item.id, type })),
  })
  const scope = effectScope()
  scope.run(() => vm.runInContext(`${stateCode}\n${nameCode}\n${filterCode}\n${listCode}\n${selectionCode}\n
    globalThis.view = { creationModelFilter, creationDisplayFilter, creationSdCardFilter,
      creationRotationFilter, filteredSavedImages, filteredSavedVideos, filteredCreationsCount };
  `, ui))
  t.after(() => scope.stop())
  return ui
}

const ids = (ui, type) => Array.from(ui.view[`filteredSaved${type}`].value, item => item.id)

test('rotation defaults to all and clearing it restores images and videos with any recorded state', t => {
  const ui = setup(t, {
    images: [creation('normal-image', 0), creation('rotated-image', 90), { id: 'legacy-image' }],
    videos: [creation('rotated-video', 270), creation('legacy-video', null)],
  })
  assert.equal(ui.view.creationRotationFilter.value, null)
  assert.deepEqual(ids(ui, 'Images'), ['normal-image', 'rotated-image', 'legacy-image'])
  assert.deepEqual(ids(ui, 'Videos'), ['rotated-video', 'legacy-video'])
  ui.view.creationRotationFilter.value = 90
  assert.equal(ui.view.filteredCreationsCount.value, 1)
  ui.view.creationRotationFilter.value = null
  assert.equal(ui.view.filteredCreationsCount.value, 5)
  assert.deepEqual(ids(ui, 'Images'), ['normal-image', 'rotated-image', 'legacy-image'])
  assert.deepEqual(ids(ui, 'Videos'), ['rotated-video', 'legacy-video'])
})

for (const rotation of [0, 90, 180, 270]) {
  test(`${rotation} degrees matches only that saved rotation for both images and videos`, t => {
    const ui = setup(t, {
      images: [0, 90, 180, 270].map(value => creation(`image-${value}`, value)),
      videos: [0, 90, 180, 270].map(value => creation(`video-${value}`, value)),
    })
    ui.view.creationRotationFilter.value = rotation
    assert.deepEqual(ids(ui, 'Images'), [`image-${rotation}`])
    assert.deepEqual(ids(ui, 'Videos'), [`video-${rotation}`])
    assert.equal(ui.view.filteredCreationsCount.value, 2)
  })
}

test('unrecorded or invalid rotations stay distinct from a recorded zero degree rotation', t => {
  const unknown = [
    { id: 'no-metadata' }, { id: 'no-rotation', metadata: {} },
    ...[null, undefined, '', '0', '90', false, true, -90, 45, 360, NaN].map((value, index) => creation(`invalid-${index}`, value)),
  ]
  const ui = setup(t, {
    images: [...unknown, creation('normal-image', 0)],
    videos: [...unknown, creation('normal-video', 0)],
  })
  ui.view.creationRotationFilter.value = '__no_rotation__'
  assert.deepEqual(ids(ui, 'Images'), unknown.map(item => item.id))
  assert.deepEqual(ids(ui, 'Videos'), unknown.map(item => item.id))
  ui.view.creationRotationFilter.value = 0
  assert.deepEqual(ids(ui, 'Images'), ['normal-image'])
  assert.deepEqual(ids(ui, 'Videos'), ['normal-video'])
})

test('rotation combines with model, display, and media-specific SD card filters', t => {
  const metadata = { model: { name: 'Selected model' }, display: { name: 'Selected screen' } }
  const items = [
    creation('shared', 90, metadata),
    creation('other-rotation', 0, metadata),
    creation('other-model', 90, { ...metadata, model: { name: 'Other model' } }),
    creation('other-display', 90, { ...metadata, display: { name: 'Other screen' } }),
    creation('no-display', 90, { model: metadata.model }),
  ]
  const ui = setup(t, { images: items, videos: items, onSdCard: [{ id: 'shared', type: 'video' }] })
  ui.view.creationRotationFilter.value = 90
  ui.view.creationModelFilter.value = 'Selected model'
  ui.view.creationDisplayFilter.value = 'Selected screen'
  assert.deepEqual(ids(ui, 'Images'), ['shared'])
  assert.deepEqual(ids(ui, 'Videos'), ['shared'])
  ui.view.creationSdCardFilter.value = 'on_sd_card'
  assert.deepEqual(ids(ui, 'Images'), [])
  assert.deepEqual(ids(ui, 'Videos'), ['shared'])
  ui.view.creationSdCardFilter.value = 'not_on_sd_card'
  assert.deepEqual(ids(ui, 'Images'), ['shared'])
  assert.deepEqual(ids(ui, 'Videos'), [])
  ui.view.creationSdCardFilter.value = null
  ui.view.creationDisplayFilter.value = '__no_display__'
  assert.deepEqual(ids(ui, 'Images'), ['no-display'])
  assert.deepEqual(ids(ui, 'Videos'), ['no-display'])
})

test('changing rotation prunes hidden selections and does not reselect them when cleared', async t => {
  const ui = setup(t, {
    images: [creation('shared', 0), creation('rotated-image', 90)],
    videos: [creation('shared', 90), creation('legacy-video', null)],
  })
  ui.selectedCreationKeys.value = [
    { id: 'shared', type: 'image' }, { id: 'rotated-image', type: 'image' },
    { id: 'shared', type: 'video' }, { id: 'legacy-video', type: 'video' },
  ].map(gallerySelectionKey)
  ui.view.creationRotationFilter.value = 90
  await nextTick()
  const remaining = [{ id: 'rotated-image', type: 'image' }, { id: 'shared', type: 'video' }].map(gallerySelectionKey)
  assert.deepEqual(Array.from(ui.selectedCreationKeys.value), remaining)
  ui.view.creationRotationFilter.value = null
  await nextTick()
  assert.deepEqual(Array.from(ui.selectedCreationKeys.value), remaining)
})
