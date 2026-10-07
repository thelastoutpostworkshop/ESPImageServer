import test from 'node:test'
import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import vm from 'node:vm'
import { sdSaveCommandEndpoint, sdSaveProgressMessage } from '../src/sdSaveProgress.js'
import { requireSdCardCommandAvailable } from '../src/sdDeletion.js'

const source = await readFile(new URL('../src/App.vue', import.meta.url), 'utf8')
function functions(start, end) {
  const from = source.indexOf(start), to = source.indexOf(end)
  assert.ok(from >= 0 && to > from, `Missing function boundary: ${start} / ${end}`)
  return source.slice(from, to)
}
const galleryCode = functions('let savedImagesLoadSequence = 0', 'function showSavedVideoActions(')
const inventoryCode = functions('async function fetchDisplaySdCardReport()', 'async function refreshDisplaySdCard()')
const manualRefreshCode = functions('async function refreshCreationLibrarySdCardStatus()', 'async function toggleMetadataPanePin()')
const imageSaveCode = functions('async function saveImageToDisplaySdCard(', 'async function saveContextMenuImageToDisplaySdCard()')
const rotationCode = functions('async function loadDisplaySettings()', 'async function setVideoRotation(')
const commandGuardCode = functions('function requireDisplayCommandAvailable()', 'let galleryBulkSaveTimer = null')

function deferred() {
  let resolve, reject
  const promise = new Promise((yes, no) => { resolve = yes; reject = no })
  return { promise, resolve, reject }
}
const response = records => ({ ok: true, json: async () => records })
const report = (version, filename) => ({ available: true, report_version: version, files: [{ name: filename }] })

// Execute production functions with controlled awaits. Every fetch is a stub;
// these tests never send a command to a connected display.
function setup() {
  const ui = vm.createContext({
    scope: '/displays/one', sdCardDisplaySelectionVersion: 0,
    display: { value: { id: 'one', name: 'First screen', connected: true, width: 320, height: 820 } },
    selectedRegisteredDisplay: { value: { id: 'one' } },
    displays: { value: [{ id: 'one' }] },
    activeDisplayOnline: { value: true },
    activeDisplayCommandUnavailableMessage: () => 'Offline',
    selectedDisplayEndpoint: suffix => ui.scope + suffix,
    savedImages: { value: [{ id: 'kept-image' }] }, savedImagesLoading: { value: false },
    savedVideos: { value: [{ id: 'kept-video' }] },
    displaySdCard: { value: report(1, 'initial.jpg') },
    displaySdCardScope: { value: '/displays/one' }, displaySdCardLoading: { value: false },
    sdCardDeletionActive: { value: false }, sdCardDeleteTarget: { value: null },
    galleryBulkSaveBusy: { value: false },
    sdCardInventoryRefreshing: { value: false },
    savingToDisplaySdCard: { value: false }, savingVideoToDisplaySdCard: { value: false },
    activeSDCardSave: { value: null },
    displayRotation: { value: 0 }, videoRotation: { value: 0 },
    error: { value: '' }, status: { value: '' }, metadataError: { value: '' },
    requireSdCardCommandAvailable, sdSaveCommandEndpoint, sdSaveProgressMessage,
    showSDCardSaveStatus: () => {}, showSDCardSnackbar: () => {},
    window: { setTimeout: callback => callback() },
    fetch: async () => assert.fail('Unexpected request'),
  })
  vm.runInContext(commandGuardCode + galleryCode + inventoryCode + manualRefreshCode + imageSaveCode, ui)
  ui.select = id => {
    ui.scope = `/displays/${encodeURIComponent(id)}`
    ui.selectedRegisteredDisplay.value = { id }
    ui.display.value = { id, name: id, connected: true, width: 320, height: 820 }
    ++ui.sdCardDisplaySelectionVersion
    vm.runInContext('++sdCardLoadSequence', ui)
    ui.displaySdCard.value = { available: false, files: [] }
    ui.displaySdCardScope.value = null
    ui.displaySdCardLoading.value = false
  }
  return ui
}

test('a bulk save prevents an inventory refresh or single image save from sending a command', async () => {
  const ui = setup()
  ui.galleryBulkSaveBusy.value = true
  await assert.rejects(ui.refreshDisplaySdCardInventory(), /bulk save to finish or cancel/)
  await ui.saveImageToDisplaySdCard({ id: 'image' })
  assert.match(ui.error.value, /bulk save to finish or cancel/)
  assert.equal(ui.savingToDisplaySdCard.value, false)
})

for (const outcome of ['success', 'failure']) {
  test(`a delayed inventory poll ${outcome} cannot replace an explicit fresh report`, async () => {
    const ui = setup(), old = deferred(), requests = []
    let reads = 0
    ui.fetch = async (url, options = {}) => {
      requests.push({ url, options })
      if (url.endsWith('/display-sd-card')) {
        if (++reads === 1) return old.promise
        return response(report(reads === 2 ? 1 : 2, 'fresh.jpg'))
      }
      return response(options.method === 'POST'
        ? { id: 'refresh', display_id: 'one' }
        : { status: 'complete', report_version: 2 })
    }
    const poll = ui.loadDisplaySdCard()
    await ui.refreshDisplaySdCardInventory()
    if (outcome === 'success') old.resolve(response(report(1, 'stale.jpg')))
    else old.reject(new Error('Old poll failed'))
    await poll
    assert.equal(ui.displaySdCard.value.report_version, 2)
    assert.equal(ui.displaySdCard.value.files[0].name, 'fresh.jpg')
    assert.equal(ui.displaySdCardLoading.value, false)
    assert.ok(requests.filter(({ options }) => options.method !== 'POST').every(({ options }) => options.cache === 'no-store'))
  })
}

test('refresh pauses its own target polls while new-target loading survives old refresh cleanup', async () => {
  const ui = setup(), initial = deferred(), newTarget = deferred(), requests = []
  ui.fetch = async url => {
    requests.push(url)
    return url.startsWith('/displays/one/') ? initial.promise : newTarget.promise
  }
  const refresh = ui.refreshDisplaySdCardInventory()
  const stopped = assert.rejects(refresh, /Active display changed/)
  await ui.loadDisplaySdCard()
  await assert.rejects(ui.refreshDisplaySdCardInventory(), /already running/)
  assert.deepEqual(requests, ['/displays/one/display-sd-card'])

  ui.select('two')
  const newPoll = ui.loadDisplaySdCard()
  assert.equal(ui.displaySdCardLoading.value, true)
  initial.resolve(response(report(1, 'old.jpg')))
  await stopped
  assert.equal(ui.displaySdCardLoading.value, true)
  assert.equal(ui.displaySdCardScope.value, null)
  newTarget.resolve(response(report(0, 'new.jpg')))
  await newPoll
  assert.equal(ui.displaySdCardScope.value, '/displays/two')
  assert.equal(ui.displaySdCard.value.files[0].name, 'new.jpg')
  assert.equal(ui.displaySdCardLoading.value, false)
  assert.deepEqual(requests, ['/displays/one/display-sd-card', '/displays/two/display-sd-card'])
})

for (const outcome of ['success', 'failure']) {
  test(`a delayed gallery ${outcome} cannot replace the latest image keys`, async () => {
    const ui = setup(), old = deferred(), fresh = deferred()
    let calls = 0
    ui.fetch = async () => ++calls === 1 ? old.promise : fresh.promise
    const first = ui.loadSavedImages({ throwOnError: true })
    const second = ui.loadSavedImages()
    fresh.resolve(response([{ id: 'image', sd_card_content_keys: ['fresh-key'] }]))
    await second
    if (outcome === 'success') old.resolve(response([{ id: 'image', sd_card_content_keys: ['stale-key'] }]))
    else old.reject(new Error('Old image request failed'))
    assert.equal(await first, null)
    assert.equal(ui.savedImages.value[0].sd_card_content_keys[0], 'fresh-key')
    assert.equal(ui.savedImagesLoading.value, false)
  })
}

test('gallery requests capture and encode their display and old completion cannot clear new loading', async () => {
  const ui = setup(), old = deferred(), fresh = deferred(), requests = []
  ui.fetch = async (url, options) => {
    requests.push({ url, options })
    return requests.length === 1 ? old.promise : fresh.promise
  }
  const first = ui.loadSavedImages()
  ui.select('screen A/2')
  const second = ui.loadSavedImages()
  old.resolve(response([{ id: 'old-display-image' }]))
  assert.equal(await first, null)
  assert.equal(ui.savedImagesLoading.value, true)
  fresh.resolve(response([{ id: 'current-display-image' }]))
  await second
  assert.deepEqual(requests.map(request => request.url), ['/saved-images?display_id=one', '/saved-images?display_id=screen%20A%2F2'])
  assert.ok(requests.every(request => request.options.cache === 'no-store'))
  assert.equal(ui.savedImages.value[0].id, 'current-display-image')
  assert.equal(ui.savedImagesLoading.value, false)
})

for (const type of ['Images', 'Videos']) {
  test(`${type.toLowerCase()} metadata failures preserve the gallery and explicit refresh can report them`, async () => {
    const ui = setup(), records = ui[`saved${type}`].value
    ui.fetch = async () => response({ invalid: 'not a list' })
    assert.equal(await ui[`loadSaved${type}`](), null)
    assert.equal(ui[`saved${type}`].value, records)
    await assert.rejects(ui[`loadSaved${type}`]({ throwOnError: true }), /Invalid .* library response/)
    ui.fetch = async () => ({ ok: false, status: 503 })
    await assert.rejects(ui[`loadSaved${type}`]({ throwOnError: true }), /503/)
    assert.equal(ui[`saved${type}`].value, records)
  })
}

test('a delayed video metadata failure does not replace a newer successful reload', async () => {
  const ui = setup(), old = deferred()
  let calls = 0
  ui.fetch = async () => ++calls === 1 ? old.promise : response([{ id: 'fresh-video', metadata: { fps: 24 } }])
  const first = ui.loadSavedVideos({ throwOnError: true })
  await ui.loadSavedVideos()
  old.reject(new Error('Old video request failed'))
  assert.equal(await first, null)
  assert.equal(ui.savedVideos.value[0].metadata.fps, 24)
})

test('manual gallery refresh reloads image and video metadata after the inventory', async () => {
  const ui = setup(), inventory = deferred(), requests = []
  ui.refreshDisplaySdCardInventory = async () => inventory.promise
  ui.fetch = async url => { requests.push(url); return response([{ id: url.includes('images') ? 'fresh-image' : 'fresh-video' }]) }
  const refresh = ui.refreshCreationLibrarySdCardStatus()
  assert.deepEqual(requests, [])
  inventory.resolve(report(2, 'fresh.jpg'))
  await refresh
  assert.deepEqual(requests, ['/saved-images?display_id=one', '/saved-videos'])
  assert.equal(ui.savedImages.value[0].id, 'fresh-image')
  assert.equal(ui.savedVideos.value[0].id, 'fresh-video')
  assert.equal(ui.metadataError.value, '')
})

test('manual gallery refresh reports metadata failure while preserving existing creations', async () => {
  const ui = setup()
  ui.refreshDisplaySdCardInventory = async () => report(2, 'fresh.jpg')
  ui.fetch = async url => url.includes('images') ? response({ invalid: true }) : response([{ id: 'fresh-video' }])
  await ui.refreshCreationLibrarySdCardStatus()
  assert.match(ui.metadataError.value, /Invalid image library response/)
  assert.equal(ui.savedImages.value[0].id, 'kept-image')
})

test('switching displays during manual refresh prevents a metadata reload and preserves the new error', async () => {
  const ui = setup(), inventory = deferred()
  ui.refreshDisplaySdCardInventory = async () => inventory.promise
  const refresh = ui.refreshCreationLibrarySdCardStatus()
  ui.select('two')
  ui.metadataError.value = 'New display error'
  inventory.resolve(report(2, 'old.jpg'))
  await refresh
  assert.equal(ui.metadataError.value, 'New display error')
  assert.equal(ui.savedImages.value[0].id, 'kept-image')
})

for (const status of ['complete', 'already_saved']) {
  test(`${status} image save reloads current inventory and gallery keys`, async () => {
    const ui = setup(), requests = []
    ui.refreshDisplaySdCardInventory = async () => report(2, 'initial.jpg')
    ui.fetch = async (url, options = {}) => {
      requests.push({ url, method: options.method || 'GET' })
      if (url.includes('/save-saved-image/')) return response({ id: 'save', display_id: 'one', status: status === 'already_saved' ? status : 'queued' })
      if (url.includes('/display-commands/')) return response({ status, detail: 'Saved' })
      if (url.endsWith('/display-sd-card')) return response(report(3, 'saved.jpg'))
      return response([{ id: 'image', sd_card_content_keys: ['saved-key'] }])
    }
    await ui.saveImageToDisplaySdCard({ id: 'image' })
    assert.equal(requests.filter(request => request.method === 'POST').length, 1)
    assert.ok(requests.some(request => request.url === '/displays/one/display-sd-card'))
    assert.ok(requests.some(request => request.url === '/saved-images?display_id=one'))
    assert.equal(ui.displaySdCard.value.files[0].name, 'saved.jpg')
    assert.equal(ui.savedImages.value[0].sd_card_content_keys[0], 'saved-key')
    assert.equal(ui.savingToDisplaySdCard.value, false)
    assert.equal(ui.activeSDCardSave.value, null)
  })
}

test('rotation saves reload gallery identities only after the server confirms the change', async () => {
  const ui = setup(), put = deferred(), requests = []
  vm.runInContext(rotationCode, ui)
  ui.fetch = async (url, options = {}) => {
    requests.push({ url, method: options.method || 'GET' })
    return options.method === 'PUT' ? put.promise : response([{ id: 'image', sd_card_content_keys: ['rotated-key'] }])
  }
  const changed = ui.setDisplayRotation(90)
  assert.equal(ui.displayRotation.value, 90)
  assert.deepEqual(requests.map(request => request.method), ['PUT'])
  put.resolve(response({ rotation: 90 }))
  await changed
  assert.deepEqual(requests.map(request => request.method), ['PUT', 'GET'])
  assert.equal(ui.savedImages.value[0].sd_card_content_keys[0], 'rotated-key')
})

for (const outcome of ['success', 'failure']) {
  test(`old-display settings ${outcome} cannot change the new display rotation`, async () => {
    const ui = setup(), old = deferred()
    vm.runInContext(rotationCode, ui)
    ui.fetch = async url => {
      if (url.startsWith('/displays/one/')) return old.promise
      return response({ rotation: url.includes('/video-display-settings') ? 270 : 180 })
    }
    const first = ui.loadDisplaySettings()
    ui.select('two')
    await ui.loadDisplaySettings()
    if (outcome === 'success') old.resolve(response({ rotation: 90 }))
    else old.reject(new Error('Old settings failed'))
    await first
    assert.equal(ui.displayRotation.value, 180)
    assert.equal(ui.videoRotation.value, 270)
  })

  test(`old rotation PUT ${outcome} cannot apply or roll back the new display state`, async () => {
    const ui = setup(), old = deferred(), requests = []
    vm.runInContext(rotationCode, ui)
    ui.fetch = async url => { requests.push(url); return old.promise }
    const changed = ui.setDisplayRotation(90)
    ui.select('two')
    ui.displayRotation.value = 180
    ui.error.value = 'New display error'
    if (outcome === 'success') old.resolve(response({ rotation: 90 }))
    else old.reject(new Error('Old PUT failed'))
    await changed
    assert.equal(ui.displayRotation.value, 180)
    assert.equal(ui.error.value, 'New display error')
    assert.deepEqual(requests, ['/displays/one/display-settings'])
  })
}
