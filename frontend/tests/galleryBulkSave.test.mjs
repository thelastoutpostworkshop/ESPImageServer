import test from 'node:test'
import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import vm from 'node:vm'
import {
  gallerySelectionKey,
  selectAllGalleryItems,
  selectedGalleryItems,
  filterGallerySelection,
  reconcileGallerySelection,
  isGalleryBulkSaveActive,
  galleryBulkSaveProgressMessage,
} from '../src/galleryBulkSave.js'

const image = { id: 'shared/id', type: 'image' }
const video = { id: 'shared/id', type: 'video' }
const other = { id: 'other', type: 'image' }

test('image and video IDs cannot collide, including punctuation in IDs', () => {
  assert.notEqual(gallerySelectionKey(image), gallerySelectionKey(video))
  assert.notEqual(gallerySelectionKey({ type: 'image', id: 'video:a' }), gallerySelectionKey({ type: 'video', id: 'image:a' }))
  assert.deepEqual(selectedGalleryItems([image, video], [gallerySelectionKey(video)]), [video])
})

test('select all uses all filtered rows once, independent of list pagination', () => {
  const items = [image, video, other, { ...image }]
  const keys = selectAllGalleryItems(items)
  assert.equal(keys.length, 3)
  assert.deepEqual(selectedGalleryItems(items, keys), [image, video, other])
})

test('filter changes discard hidden selections and keep visible image/video IDs distinct', () => {
  const keys = selectAllGalleryItems([image, video, other])
  assert.deepEqual(filterGallerySelection(keys, [video]), [gallerySelectionKey(video)])
  assert.deepEqual(selectedGalleryItems([video], keys), [video])
  assert.deepEqual(filterGallerySelection(keys, []), [])
})

test('only confirmed saved and already-saved entries leave the selection', () => {
  const items = [image, video, other,
    { type: 'video', id: 'cancelled' }, { type: 'image', id: 'failed' }, { type: 'video', id: 'saving' }]
  const statuses = ['saved', 'already_saved', 'queued', 'cancelled', 'failed', 'saving']
  const batch = { items: items.map((item, index) => ({ ...item, status: statuses[index] })) }
  assert.deepEqual(reconcileGallerySelection(selectAllGalleryItems(items), batch), selectAllGalleryItems(items.slice(2)))
  assert.deepEqual(reconcileGallerySelection(selectAllGalleryItems(items), null), selectAllGalleryItems(items))
})

test('a requested cancellation stays active until the display confirms it stopped', () => {
  assert.equal(isGalleryBulkSaveActive({ status: 'running' }), true)
  assert.equal(isGalleryBulkSaveActive({ status: 'cancelling' }), true)
  for (const status of ['complete', 'cancelled', 'failed']) assert.equal(isGalleryBulkSaveActive({ status }), false)
  assert.equal(isGalleryBulkSaveActive(null), false)
  assert.match(galleryBulkSaveProgressMessage({ status: 'cancelling', total: 3, saved: 1, skipped: 0 }), /waiting for the display to stop/)
})

test('progress uses one-based item position and the current download confirmation stage', () => {
  const batch = { status: 'running', total: 4, current_index: 2, saved: 1, skipped: 0,
    current_command: { progress: { stage: 'downloading', received_bytes: 30, total_bytes: 100 } } }
  assert.match(galleryBulkSaveProgressMessage(batch), /Saving item 2 of 4.*30% received/)
  assert.match(galleryBulkSaveProgressMessage({ ...batch, current_command: { progress: { stage: 'verifying' } } }), /Checking the file/)
  assert.match(galleryBulkSaveProgressMessage({ ...batch, current_index: 0, current_command: null }), /Checking SD card.*4 selected/)
  assert.equal(galleryBulkSaveProgressMessage(null), '')
})

test('terminal progress reports confirmed counts and preserves unconfirmed items for retry', () => {
  const batch = { total: 5, saved: 2, skipped: 1 }
  assert.match(galleryBulkSaveProgressMessage({ ...batch, status: 'cancelled' }), /cancelled.*2 saved, 1 already on the SD card, 2 remaining/)
  assert.match(galleryBulkSaveProgressMessage({ ...batch, status: 'failed', detail: 'Display disconnected.' }), /stopped.*2 remaining.*Display disconnected/)
  assert.match(galleryBulkSaveProgressMessage({ ...batch, total: 3, status: 'complete' }), /complete.*0 remaining/)
})

// Exercise the production request lifecycle with deferred responses. All fetches
// are stubs; no requests or display commands leave this test process.
const appSource = await readFile(new URL('../src/App.vue', import.meta.url), 'utf8')
const bulkCode = appSource.slice(appSource.indexOf('let galleryBulkSaveTimer = null'), appSource.indexOf('function activeDisplayCommandUnavailableMessage()'))
function deferred() {
  let resolve, reject
  const promise = new Promise((yes, no) => { resolve = yes; reject = no })
  return { promise, resolve, reject }
}
const response = batch => ({ ok: true, json: async () => batch })
function snapshot(status, overrides = {}) {
  return { id: 'batch/1', display_id: 'one', display_name: 'First screen', status,
    total: 2, saved: 0, skipped: 0, completed: 0, current_index: 0,
    items: [{ ...image, status: 'queued' }, { ...video, status: 'queued' }], ...overrides }
}
function setupBulk(batch = null) {
  const ui = vm.createContext({
    scope: '/displays/one', display: { value: { connected: true } },
    galleryBulkSave: { value: batch }, galleryBulkSaveLoading: { value: false },
    galleryBulkSaveStarting: { value: false }, galleryBulkSaveCancelling: { value: false },
    galleryBulkSaveError: { value: '' },
    galleryBulkSavePollError: { value: '' },
    galleryBulkSaveActive: { get value() { return isGalleryBulkSaveActive(ui.galleryBulkSave.value) } },
    selectedCreationKeys: { value: selectAllGalleryItems([image, video]) },
    selectedGalleryCreations: { value: [image, video] },
    canStartGalleryBulkSave: { value: true }, imageLibraryView: { value: 'list' },
    selectedDisplayEndpoint: suffix => ui.scope + suffix,
    reconcileGallerySelection, isGalleryBulkSaveActive,
    loadDisplaySdCard: async () => {}, loadSavedImages: async () => {}, loadSavedVideos: async () => {},
    AbortSignal: { timeout: () => undefined },
    fetch: async () => assert.fail('Unexpected request'),
  })
  vm.runInContext(bulkCode, ui)
  const poll = ui.loadGalleryBulkSave
  ui.loadGalleryBulkSave = (...args) => { ui.lastPoll = poll(...args); return ui.lastPoll }
  ui.select = scope => {
    ui.scope = scope
    vm.runInContext('++galleryBulkSaveRequestVersion', ui)
    ui.galleryBulkSave.value = null
    ui.galleryBulkSaveError.value = ''
    ui.galleryBulkSavePollError.value = ''
  }
  return ui
}

for (const oldFinishesFirst of [true, false]) {
  test(`a forced newer poll owns the snapshot and cleanup (old finishes first: ${oldFinishesFirst})`, async () => {
    const ui = setupBulk(), old = deferred(), fresh = deferred()
    let calls = 0
    ui.fetch = async () => ++calls === 1 ? old.promise : fresh.promise
    const first = ui.loadGalleryBulkSave(true)
    const second = ui.loadGalleryBulkSave(true)
    if (oldFinishesFirst) {
      old.resolve(response(snapshot('running')))
      await first
      assert.equal(ui.galleryBulkSave.value, null)
      assert.equal(ui.galleryBulkSaveLoading.value, true)
      assert.equal(vm.runInContext('galleryBulkSavePollInFlight', ui), true)
    }
    fresh.resolve(response(snapshot('complete', { completed: 2, saved: 2 })))
    await second
    if (!oldFinishesFirst) {
      old.resolve(response(snapshot('running')))
      await first
    }
    assert.equal(ui.galleryBulkSave.value.status, 'complete')
    assert.equal(ui.galleryBulkSaveLoading.value, false)
    assert.equal(vm.runInContext('galleryBulkSavePollInFlight', ui), false)
  })
}

test('cancellation before item download stays active until the follow-up poll confirms it', async () => {
  const ui = setupBulk(snapshot('running')), confirmation = deferred(), requests = []
  ui.fetch = async (url, options) => {
    requests.push({ url, method: options.method || 'GET' })
    return options.method === 'POST' ? response(snapshot('cancelling')) : confirmation.promise
  }
  await ui.cancelGalleryBulkSave()
  assert.equal(ui.galleryBulkSave.value.current_index, 0)
  assert.equal(ui.galleryBulkSave.value.status, 'cancelling')
  assert.equal(ui.galleryBulkSaveActive.value, true)
  assert.match(galleryBulkSaveProgressMessage(ui.galleryBulkSave.value), /waiting for the display to stop/)
  assert.deepEqual(requests, [
    { url: '/displays/one/sd-card-save-batches/batch%2F1/cancel', method: 'POST' },
    { url: '/displays/one/sd-card-save-batches/batch%2F1', method: 'GET' },
  ])
  confirmation.resolve(response(snapshot('cancelled')))
  await ui.lastPoll
  assert.equal(ui.galleryBulkSaveActive.value, false)
  assert.deepEqual(ui.selectedCreationKeys.value, selectAllGalleryItems([image, video]))
})

test('a cancellation invalidates an older running snapshot', async () => {
  const ui = setupBulk(snapshot('running')), old = deferred(), requests = []
  ui.fetch = async (url, options) => {
    requests.push({ url, method: options.method || 'GET' })
    return requests.length === 1 ? old.promise : response(snapshot('cancelled'))
  }
  const first = ui.loadGalleryBulkSave(true)
  await ui.cancelGalleryBulkSave()
  await ui.lastPoll
  old.resolve(response(snapshot('running')))
  await first
  assert.equal(ui.galleryBulkSave.value.status, 'cancelled')
  assert.equal(requests.filter(request => request.method === 'POST').length, 1)
})

test('display changes during cancellation keep its POST bound to the original display', async () => {
  const ui = setupBulk(snapshot('running')), cancel = deferred(), requests = []
  ui.fetch = async (url, options) => {
    requests.push({ url, method: options.method || 'GET' })
    return options.method === 'POST' ? cancel.promise : response(snapshot('running', { id: 'other', display_id: 'two' }))
  }
  const cancelling = ui.cancelGalleryBulkSave()
  ui.select('/displays/two')
  cancel.resolve(response(snapshot('cancelled')))
  await cancelling
  await ui.lastPoll
  assert.equal(ui.galleryBulkSave.value.display_id, 'two')
  assert.deepEqual(requests, [
    { url: '/displays/one/sd-card-save-batches/batch%2F1/cancel', method: 'POST' },
    { url: '/displays/two/sd-card-save-batches/active', method: 'GET' },
  ])
})

test('a lost start response recovers the existing batch without submitting the items again', async () => {
  const ui = setupBulk(), requests = []
  ui.fetch = async (url, options) => {
    requests.push({ url, method: options.method || 'GET', body: options.body })
    if (options.method === 'POST') throw new Error('Response lost')
    return response(snapshot('running'))
  }
  await ui.saveSelectedCreationsToSdCard()
  await ui.lastPoll
  assert.equal(ui.galleryBulkSave.value.status, 'running')
  assert.equal(ui.galleryBulkSaveError.value, '')
  assert.deepEqual(JSON.parse(requests[0].body).items, [image, video])
  assert.deepEqual(requests.map(request => request.method), ['POST', 'GET'])
})

test('a rejected start remains visible when the recovery poll finds no active batch', async () => {
  const ui = setupBulk()
  ui.fetch = async (_url, options) => options.method === 'POST'
    ? { ok: false, status: 409, json: async () => ({ detail: 'This display needs newer firmware.' }) }
    : response(null)
  await ui.saveSelectedCreationsToSdCard()
  await ui.lastPoll
  assert.equal(ui.galleryBulkSave.value, null)
  assert.match(ui.galleryBulkSaveError.value, /This display needs newer firmware/)
  assert.equal(ui.galleryBulkSavePollError.value, '')
  assert.equal(ui.galleryBulkSaveStarting.value, false)
})

test('the thumbnail view cannot start a bulk save', async () => {
  const ui = setupBulk()
  ui.imageLibraryView.value = 'thumbnails'
  await ui.saveSelectedCreationsToSdCard()
  assert.equal(ui.galleryBulkSaveStarting.value, false)
  assert.equal(ui.galleryBulkSave.value, null)
})
