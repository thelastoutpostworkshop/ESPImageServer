import test from 'node:test'
import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import vm from 'node:vm'

const source = await readFile(new URL('../src/App.vue', import.meta.url), 'utf8')
function functionCode(name) {
  const start = source.indexOf('function ' + name + '(')
  const end = source.indexOf('\n}', start)
  assert.ok(start >= 0 && end > start, 'Missing function: ' + name)
  return source.slice(start, end + 2)
}
const start = source.indexOf('function displaySdCardFiles()')
const end = source.indexOf('function setSdCardFileSelected(')
assert.ok(start >= 0 && end > start, 'Missing filter/selection block')
const filterCode = source.slice(start, end)

// Execute the real computed selectors and watch callbacks with in-memory
// inventory. These tests never fetch, delete files, or send device commands.
function setup(files = []) {
  const watchers = new Map()
  const ui = vm.createContext({
    displaySdCard: { value: { available: true, files } },
    sdCardMediaFilter: { value: 'all' }, sdCardPage: { value: 1 },
    selectedSdCardFileNames: { value: [] },
    computed: callback => ({ get value() { return callback() } }),
    watch: (dependency, callback) => watchers.set(dependency, callback),
  })
  vm.runInContext(functionCode('displaySdCardMediaType') + '\n' + filterCode + '\n' + functionCode('removeSdCardFilesFromInventory'), ui)
  const computed = vm.runInContext('({ filteredSdCardFiles, selectedSdCardFiles, sdCardEmptyMessage })', ui)
  ui.visible = () => Array.from(computed.filteredSdCardFiles.value, file => file.name)
  ui.selected = () => Array.from(computed.selectedSdCardFiles.value, file => file.name)
  ui.emptyMessage = () => computed.sdCardEmptyMessage.value
  ui.pruneSelection = () => watchers.get(computed.filteredSdCardFiles)(computed.filteredSdCardFiles.value)
  ui.changeFilter = filter => {
    const previous = ui.sdCardMediaFilter.value
    ui.sdCardMediaFilter.value = filter
    watchers.get(ui.sdCardMediaFilter)(filter, previous)
    ui.pruneSelection()
  }
  return ui
}
const picture = { name: 'picture.jpg', type: 'image' }
const video = { name: 'video.mjpeg', type: 'video' }
const legacyPicture = { name: 'legacy.jpg' }
const legacyVideo = { name: 'legacy.mjpeg' }
const typedVideo = { name: 'custom-name.jpg', type: 'video' }
const inventory = [picture, video, legacyPicture, legacyVideo, typedVideo]

test('All/Pictures/Videos classify inventory using the same legacy fallback as deletion', () => {
  const ui = setup(inventory)
  assert.deepEqual(ui.visible(), inventory.map(file => file.name))
  ui.changeFilter('image')
  assert.deepEqual(ui.visible(), ['picture.jpg', 'legacy.jpg'])
  ui.changeFilter('video')
  assert.deepEqual(ui.visible(), ['video.mjpeg', 'legacy.mjpeg', 'custom-name.jpg'])
  ui.changeFilter('all')
  assert.deepEqual(ui.visible(), inventory.map(file => file.name))
  assert.equal(ui.displaySdCard.value.files, inventory)
})

test('hidden media cannot enter selected deletion targets even before the pruning watcher runs', () => {
  const ui = setup(inventory)
  ui.selectedSdCardFileNames.value = ['picture.jpg', 'video.mjpeg']
  ui.sdCardMediaFilter.value = 'image'
  assert.deepEqual(ui.selected(), ['picture.jpg'])
  ui.pruneSelection()
  assert.deepEqual(Array.from(ui.selectedSdCardFileNames.value), ['picture.jpg'])
  ui.changeFilter('all')
  assert.deepEqual(ui.selected(), ['picture.jpg'])
})

test('new inventory prunes vanished selections without selecting new matching files', () => {
  const ui = setup(inventory)
  ui.changeFilter('video')
  ui.selectedSdCardFileNames.value = ['video.mjpeg', 'legacy.mjpeg']
  ui.displaySdCard.value = { available: true, files: [legacyVideo, { name: 'new.mjpeg', type: 'video' }] }
  ui.pruneSelection()
  assert.deepEqual(ui.visible(), ['legacy.mjpeg', 'new.mjpeg'])
  assert.deepEqual(ui.selected(), ['legacy.mjpeg'])
})

test('removing a filtered picture preserves videos hidden by the current filter', () => {
  const ui = setup(inventory)
  ui.selectedSdCardFileNames.value = ['picture.jpg', 'video.mjpeg']
  ui.changeFilter('image')
  ui.removeSdCardFilesFromInventory([picture])
  assert.deepEqual(Array.from(ui.displaySdCard.value.files, file => file.name), inventory.slice(1).map(file => file.name))
  assert.deepEqual(ui.visible(), ['legacy.jpg'])
  assert.deepEqual(Array.from(ui.selectedSdCardFileNames.value), [])
  ui.changeFilter('video')
  assert.deepEqual(ui.visible(), ['video.mjpeg', 'legacy.mjpeg', 'custom-name.jpg'])
})

test('changing the media filter resets the desktop table to its first page', () => {
  const ui = setup(inventory)
  ui.sdCardPage.value = 7
  ui.changeFilter('image')
  assert.equal(ui.sdCardPage.value, 1)
  ui.sdCardPage.value = 3
  ui.changeFilter('video')
  assert.equal(ui.sdCardPage.value, 1)
})

test('empty messages distinguish an empty SD card from a filter with no matches', () => {
  const empty = setup()
  assert.equal(empty.emptyMessage(), 'No saved SD card images or videos yet.')
  empty.changeFilter('video')
  assert.equal(empty.emptyMessage(), 'No saved SD card images or videos yet.')
  const pictures = setup([picture])
  pictures.changeFilter('video')
  assert.deepEqual(pictures.visible(), [])
  assert.equal(pictures.emptyMessage(), 'No videos match this filter.')
  const videos = setup([video])
  videos.changeFilter('image')
  assert.deepEqual(videos.visible(), [])
  assert.equal(videos.emptyMessage(), 'No pictures match this filter.')
})
