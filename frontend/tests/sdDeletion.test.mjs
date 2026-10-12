import test from 'node:test'
import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import vm from 'node:vm'
import { sdSaveCommandEndpoint } from '../src/sdSaveProgress.js'
import { requireSdCardCommandAvailable, waitForSdCardDeletion } from '../src/sdDeletion.js'
import { displayExperienceDefaults } from '../src/displayExperience.js'

const source = await readFile(new URL('../src/App.vue', import.meta.url), 'utf8')
const deletionCode = source.slice(source.indexOf('function displaySdCardMediaType('), source.indexOf('async function showSDCardFileOnDisplay('))
const selectionWatcherCode = source.slice(source.indexOf('watch(activeDisplayId,'), source.indexOf('const displayMessage = computed('))
const commandGuardCode = source.slice(source.indexOf('function requireDisplayCommandAvailable()'), source.indexOf('let galleryBulkSaveTimer = null'))

function deferred() {
  let resolve
  const promise = new Promise(complete => { resolve = complete })
  return { promise, resolve }
}

// Execute the real confirmation, deletion, and selection-change functions with
// controlled network awaits. No actual device receives a deletion command.
function setup({ status = 'complete', onPreferenceSave, onDelete, onPoll, onInventory, legacy = false } = {}) {
  let scope = legacy ? '' : '/displays/one'
  let selectionWatcher
  let commandCount = 0
  const requests = []
  const inventoryRequests = []
  const statusCaches = []
  let elapsed = 0
  const notifications = []
  const loads = []
  const files = [{ name: 'a.jpg', type: 'image' }, { name: 'b.mjpeg', type: 'video' }]
  const firstDisplay = { id: legacy ? undefined : 'one', name: 'First screen', connected: true, online: true }
  const ui = vm.createContext({
    activeDisplayId: { value: legacy ? '' : 'one' },
    selectedRegisteredDisplay: { value: legacy ? null : firstDisplay },
    display: { value: firstDisplay },
    activeDisplayOnline: { value: true },
    activeDisplayCommandUnavailableMessage: () => 'Offline',
    selectedDisplayEndpoint: suffix => scope + suffix,
    sdSaveCommandEndpoint,
    sdCardDisplaySelectionVersion: 0,
    sdCardDeleteTarget: { value: null },
    sdCardDeleteProgress: { value: null },
    sdCardDeletionActive: { get value() { return ui.deletingSdCardFile.value || ui.deletingSdCardFiles.value } },
    sdCardInventoryRefreshing: { value: false },
    galleryBulkSaveBusy: { value: false },
    galleryBulkSaveRequestVersion: 0,
    galleryBulkSave: { value: null },
    galleryBulkSaveError: { value: '' },
    galleryBulkSavePollError: { value: '' },
    selectedCreationKeys: { value: [] },
    loadGalleryBulkSave: () => {},
    savingToDisplaySdCard: { value: false },
    savingVideoToDisplaySdCard: { value: false },
    displayingSdCardFile: { value: '' },
    displayExperienceSaving: { value: false },
    displayExperienceLoadSequence: 0,
    displayExperience: { value: displayExperienceDefaults() },
    reportedDisplayExperience: { value: null },
    displayExperienceLoading: { value: false },
    displayExperienceDefaults,
    displayExperiencePreviewChanging: { value: false },
    requireSdCardCommandAvailable,
    AbortSignal,
    waitForSdCardDeletion: options => waitForSdCardDeletion({ ...options, now: () => elapsed, wait: async ms => { elapsed += ms } }),
    sdCardLoadSequence: 0,
    sdCardRefreshTarget: null,
    displaySdCardLoading: { value: true },
    displaySdCardScope: { value: scope },
    displaySdCard: { value: { available: true, files } },
    selectedSdCardFileNames: { value: ['a.jpg', 'b.mjpeg'] },
    sdCardFileToDelete: { value: null },
    sdCardFilesToDelete: { value: [] },
    deleteSdCardFileDialog: { value: false },
    deleteSdCardFilesDialog: { value: false },
    deleteSdCardFileDontAskAgain: { value: false },
    deleteSdCardFilesDontAskAgain: { value: false },
    deletingSdCardFile: { value: false },
    deletingSdCardFiles: { value: false },
    confirmDeletion: { value: true },
    error: { value: '' },
    displayExperiencePreviewing: { value: false },
    displayRotation: { value: 0 },
    videoRotation: { value: 0 },
    page: { value: 'sd-card' },
    loadDisplaySettings: () => {},
    loadSavedImages: () => {},
    loadDisplayExperience: () => {},
    displaySdCardFiles: () => ui.displaySdCard.value.files || [],
    selectedSdCardFiles: {
      get value() {
        return ui.displaySdCard.value.files.filter(file => ui.selectedSdCardFileNames.value.includes(file.name))
      },
    },
    setDeleteConfirmation: async value => {
      await onPreferenceSave?.(ui)
      ui.confirmDeletion.value = value
    },
    loadDisplaySdCard: async () => {
      loads.push(scope)
      ui.displaySdCardLoading.value = true
    },
    showSDCardSnackbar: message => notifications.push(message),
    watch: (_ref, callback) => { selectionWatcher = callback },
    window: {
      setTimeout: callback => callback(),
      localStorage: { setItem: () => {}, removeItem: () => {} },
    },
    activeDisplaySettingsKey: 'active-display',
    fetch: async (url, options = {}) => {
      const request = { url, method: options.method || 'GET' }
      if (request.method === 'GET' && url.endsWith('/display-sd-card')) {
        inventoryRequests.push({ ...request, cache: options.cache })
        const report = await onInventory?.(ui, request) || { available: true, report_version: 1, files: [...ui.displaySdCard.value.files] }
        return { ok: true, json: async () => report }
      }
      requests.push(request)
      if (request.method === 'DELETE') {
        const command = {
          id: `delete-${++commandCount}`,
          display_id: url.startsWith('/displays/') ? decodeURIComponent(url.split('/')[2]) : '__legacy__',
        }
        await onDelete?.(ui, request)
        return { ok: true, json: async () => command }
      }
      statusCaches.push(options.cache)
      const result = await onPoll?.(ui, request) || status
      if (typeof result === 'object') return { ok: !result.httpStatus, status: result.httpStatus, json: async () => result }
      return { ok: true, json: async () => ({ status: result, detail: result === 'complete' ? 'Deleted' : 'Could not delete' }) }
    },
  })
  vm.runInContext(commandGuardCode + deletionCode + '\n' + selectionWatcherCode, ui)
  ui.selectDisplay = (id, { installInventory = true } = {}) => {
    const previousId = ui.activeDisplayId.value
    scope = id ? `/displays/${encodeURIComponent(id)}` : ''
    const target = { id: id || undefined, name: id === 'one' ? 'First screen' : 'Second screen', connected: true, online: true }
    ui.activeDisplayId.value = id
    ui.selectedRegisteredDisplay.value = id ? target : null
    ui.display.value = target
    selectionWatcher(id, previousId)
    if (installInventory) {
      ui.displaySdCard.value = { available: true, files: [{ name: 'a.jpg', type: 'image' }, { name: 'other.jpg', type: 'image' }] }
      ui.displaySdCardScope.value = scope
      ui.selectedSdCardFileNames.value = ['a.jpg']
      ui.displaySdCardLoading.value = true
    }
  }
  return { ui, files, requests, inventoryRequests, statusCaches, notifications, loads, get elapsed() { return elapsed } }
}

test('confirmed deletion removes the file only after acknowledgement and invalidates older loads', async () => {
  const { ui, files, requests } = setup()
  const target = ui.captureSdCardDeleteTarget([files[0]])
  await ui.deleteSdCardFileAndWait(files[0], target)
  assert.equal(ui.displaySdCard.value.files.length, 1)
  assert.equal(ui.displaySdCard.value.files[0].name, 'b.mjpeg')
  assert.equal(ui.displaySdCard.value.inventory_refresh_pending, true)
  assert.equal(ui.sdCardLoadSequence, 1)
  assert.deepEqual(requests, [
    { url: '/displays/one/display-sd-card/files/a.jpg', method: 'DELETE' },
    { url: '/displays/one/display-commands/delete-1', method: 'GET' },
  ])
})

for (const status of ['failed', 'superseded', 'cancelled']) {
  test(`${status} deletion keeps the file visible`, async () => {
    const { ui, files } = setup({ status })
    const target = ui.captureSdCardDeleteTarget([files[0]])
    await assert.rejects(ui.deleteSdCardFileAndWait(files[0], target))
    assert.equal(ui.displaySdCard.value.files.length, 2)
    assert.equal(ui.displaySdCard.value.inventory_refresh_pending, undefined)
  })
}

for (const bulk of [false, true]) {
  const label = bulk ? 'bulk' : 'single-file'
  test(`switching displays invalidates an open ${label} confirmation before any DELETE`, async () => {
    const { ui, files, requests } = setup()
    if (bulk) ui.confirmDeleteSelectedSdCardFiles()
    else ui.confirmDeleteDisplaySdCardFile(files[0])
    const dialog = bulk ? ui.deleteSdCardFilesDialog : ui.deleteSdCardFileDialog
    assert.equal(dialog.value, true)
    assert.equal(ui.sdCardDeleteTarget.value.scope, '/displays/one')
    ui.selectDisplay('two')
    assert.equal(dialog.value, false)
    assert.equal(ui.sdCardDeleteTarget.value, null)
    if (bulk) await ui.deleteSelectedDisplaySdCardFiles()
    else await ui.deleteDisplaySdCardFile()
    assert.deepEqual(requests, [])
    assert.equal(ui.displaySdCard.value.files.length, 2)
  })

  test(`switching during the ${label} preferences await cannot redirect deletion`, async () => {
    const preference = deferred()
    const { ui, files, requests } = setup({ onPreferenceSave: () => preference.promise })
    if (bulk) {
      ui.confirmDeleteSelectedSdCardFiles()
      ui.deleteSdCardFilesDontAskAgain.value = true
    } else {
      ui.confirmDeleteDisplaySdCardFile(files[0])
      ui.deleteSdCardFileDontAskAgain.value = true
    }
    const deletion = bulk ? ui.deleteSelectedDisplaySdCardFiles() : ui.deleteDisplaySdCardFile()
    ui.selectDisplay('two')
    const secondInventory = ui.displaySdCard.value
    preference.resolve()
    await deletion
    assert.deepEqual(requests, [])
    assert.strictEqual(ui.displaySdCard.value, secondInventory)
    assert.equal(ui.displaySdCardLoading.value, true)
  })
}

test('switching between bulk items stops unsent requests instead of deleting the same name on another display', async () => {
  let switched = false
  const { ui, requests, loads } = setup({
    onPoll: current => {
      if (!switched) {
        switched = true
        current.selectDisplay('two')
      }
    },
  })
  ui.confirmDeleteSelectedSdCardFiles()
  await ui.deleteSelectedDisplaySdCardFiles()
  assert.deepEqual(requests, [
    { url: '/displays/one/display-sd-card/files/a.jpg', method: 'DELETE' },
    { url: '/displays/one/display-commands/delete-1', method: 'GET' },
  ])
  assert.deepEqual(Array.from(ui.displaySdCard.value.files, file => file.name), ['a.jpg', 'other.jpg'])
  assert.equal(ui.displaySdCard.value.inventory_refresh_pending, undefined)
  assert.match(ui.error.value, /First screen|original display/i)
  assert.match(ui.error.value, /1 of 2/)
  assert.deepEqual(loads, ['/displays/two'])
})

test('a dispatched deletion keeps polling its original display after selection changes without changing the new inventory', async () => {
  const { ui, files, requests } = setup({ onDelete: current => current.selectDisplay('two') })
  const target = ui.captureSdCardDeleteTarget([files[0]])
  const deletion = ui.deleteSdCardFileAndWait(files[0], target)
  while (!requests.some(request => request.method === 'DELETE')) await Promise.resolve()
  const secondInventory = ui.displaySdCard.value
  const secondLoadSequence = ui.sdCardLoadSequence
  await deletion
  assert.deepEqual(requests, [
    { url: '/displays/one/display-sd-card/files/a.jpg', method: 'DELETE' },
    { url: '/displays/one/display-commands/delete-1', method: 'GET' },
  ])
  assert.strictEqual(ui.displaySdCard.value, secondInventory)
  assert.equal(ui.sdCardLoadSequence, secondLoadSequence)
  assert.equal(ui.displaySdCardLoading.value, true)
  assert.deepEqual(Array.from(ui.selectedSdCardFileNames.value), ['a.jpg'])
})

test('switching during command polling keeps subsequent status requests on the original display', async () => {
  let polls = 0
  const { ui, files, requests } = setup({
    onPoll: current => {
      if (++polls === 1) {
        current.selectDisplay('two')
        return 'pending'
      }
      return 'complete'
    },
  })
  const target = ui.captureSdCardDeleteTarget([files[0]])
  await ui.deleteSdCardFileAndWait(files[0], target)
  assert.deepEqual(requests, [
    { url: '/displays/one/display-sd-card/files/a.jpg', method: 'DELETE' },
    { url: '/displays/one/display-commands/delete-1', method: 'GET' },
    { url: '/displays/one/display-commands/delete-1', method: 'GET' },
  ])
  assert.deepEqual(Array.from(ui.displaySdCard.value.files, file => file.name), ['a.jpg', 'other.jpg'])
  assert.equal(ui.displaySdCard.value.inventory_refresh_pending, undefined)
  assert.equal(ui.displaySdCardLoading.value, true)
})

test('single-file completion names the original display and does not refresh the new selection', async () => {
  const { ui, files, notifications, loads } = setup({ onDelete: current => current.selectDisplay('two') })
  ui.confirmDeleteDisplaySdCardFile(files[0])
  await ui.deleteDisplaySdCardFile()
  assert.equal(notifications.length, 1)
  assert.match(notifications[0], /First screen/)
  assert.doesNotMatch(notifications[0], /Second screen/)
  assert.deepEqual(loads, ['/displays/two'])
  assert.deepEqual(Array.from(ui.displaySdCard.value.files, file => file.name), ['a.jpg', 'other.jpg'])
})

for (const bulk of [false, true]) {
  test(`confirmation-disabled ${bulk ? 'bulk' : 'single-file'} deletion retains its original display`, async () => {
    const { ui, files, requests } = setup({ onDelete: current => current.selectDisplay('two') })
    ui.confirmDeletion.value = false
    const functionName = bulk ? 'deleteSelectedDisplaySdCardFiles' : 'deleteDisplaySdCardFile'
    const deleteFunction = ui[functionName]
    let deletion
    ui[functionName] = (...args) => { deletion = deleteFunction(...args); return deletion }
    if (bulk) ui.confirmDeleteSelectedSdCardFiles()
    else ui.confirmDeleteDisplaySdCardFile(files[0])
    assert.ok(deletion)
    await deletion
    assert.deepEqual(requests, [
      { url: '/displays/one/display-sd-card/files/a.jpg', method: 'DELETE' },
      { url: '/displays/one/display-commands/delete-1', method: 'GET' },
    ])
    assert.deepEqual(Array.from(ui.displaySdCard.value.files, file => file.name), ['a.jpg', 'other.jpg'])
    assert.equal(ui.deleteSdCardFileDialog.value, false)
    assert.equal(ui.deleteSdCardFilesDialog.value, false)
  })
}

test('bulk deletion uses the filenames confirmed before its preferences await', async () => {
  const preference = deferred()
  const { ui, files, requests } = setup({ onPreferenceSave: () => preference.promise })
  ui.confirmDeleteSelectedSdCardFiles()
  ui.deleteSdCardFilesDontAskAgain.value = true
  const deletion = ui.deleteSelectedDisplaySdCardFiles()
  files[0].name = 'replacement.jpg'
  files[1].name = 'replacement.mjpeg'
  preference.resolve()
  await deletion
  assert.deepEqual(requests.filter(request => request.method === 'DELETE'), [
    { url: '/displays/one/display-sd-card/files/a.jpg', method: 'DELETE' },
    { url: '/displays/one/display-sd-card/files/b.mjpeg', method: 'DELETE' },
  ])
})

test('switching away and back while saving preferences still invalidates the original confirmation', async () => {
  const preference = deferred()
  const { ui, files, requests } = setup({ onPreferenceSave: () => preference.promise })
  ui.confirmDeleteDisplaySdCardFile(files[0])
  ui.deleteSdCardFileDontAskAgain.value = true
  const deletion = ui.deleteDisplaySdCardFile()
  ui.selectDisplay('two')
  ui.selectDisplay('one')
  preference.resolve()
  await deletion
  assert.deepEqual(requests, [])
})

test('an inventory belonging to the previous display cannot start deletion on the current display', () => {
  const { ui, files, requests } = setup()
  ui.selectDisplay('two', { installInventory: false })
  ui.displaySdCard.value = { available: true, files }
  ui.displaySdCardScope.value = '/displays/one'
  ui.confirmDeleteDisplaySdCardFile(files[0])
  assert.equal(ui.sdCardDeleteTarget.value, null)
  assert.equal(ui.deleteSdCardFileDialog.value, false)
  assert.deepEqual(requests, [])
})

test('a stale row handler cannot delete a file even when the current inventory reuses its filename', () => {
  const { ui, files, requests } = setup()
  ui.displaySdCard.value = { available: true, files: [{ ...files[0] }] }
  ui.confirmDeleteDisplaySdCardFile(files[0])
  assert.equal(ui.sdCardDeleteTarget.value, null)
  assert.equal(ui.deleteSdCardFileDialog.value, false)
  assert.deepEqual(requests, [])
})

test('legacy display deletion retains the legacy endpoints', async () => {
  const { ui, files, requests } = setup({ legacy: true })
  const target = ui.captureSdCardDeleteTarget([files[0]])
  await ui.deleteSdCardFileAndWait(files[0], target)
  assert.deepEqual(requests, [
    { url: '/display-sd-card/files/a.jpg', method: 'DELETE' },
    { url: '/display-commands/delete-1', method: 'GET' },
  ])
})

test('bulk deletion waits beyond the old 15-second limit and reports real completed progress', async () => {
  let secondPolls = 0
  const run = setup({ onPoll: (_ui, request) => request.url.endsWith('delete-2') && ++secondPolls <= 44 ? 'pending' : 'complete' })
  run.ui.confirmDeleteSelectedSdCardFiles()
  await run.ui.deleteSelectedDisplaySdCardFiles()
  assert.equal(run.ui.sdCardDeleteProgress.value.completed, 2)
  assert.equal(run.ui.sdCardDeleteProgress.value.total, 2)
  assert.equal(run.ui.sdCardDeleteProgress.value.state, 'complete')
  assert.ok(run.elapsed > 15000)
  assert.equal(run.requests.filter(request => request.method === 'DELETE').length, 2)
  assert.ok(run.statusCaches.every(cache => cache === 'no-store'))
  assert.ok(run.inventoryRequests.every(request => request.cache === 'no-store'))
  assert.equal(run.ui.error.value, '')
})

test('a transient connection error and HTTP failure retry status without resending deletion', async () => {
  let polls = 0
  const run = setup({ onPoll: () => {
    if (++polls === 1) throw new Error('Connection reset')
    if (polls === 2) return { httpStatus: 503 }
    return 'complete'
  } })
  run.ui.confirmDeleteDisplaySdCardFile(run.files[0])
  await run.ui.deleteDisplaySdCardFile()
  assert.equal(polls, 3)
  assert.equal(run.requests.filter(request => request.method === 'DELETE').length, 1)
  assert.equal(run.ui.sdCardDeleteProgress.value.completed, 1)
  assert.equal(run.ui.sdCardDeleteProgress.value.state, 'complete')
})

test('a fresh complete inventory confirms missing acknowledgements and keeps bulk deletion serial', async () => {
  let inventoryReads = 0
  const run = setup({ status: 'pending', onInventory: () => {
    ++inventoryReads
    const version = inventoryReads === 1 ? 1 : inventoryReads < 4 ? 2 : 3
    const files = inventoryReads === 1 ? [{ name: 'a.jpg' }, { name: 'b.mjpeg' }] : inventoryReads < 4 ? [{ name: 'b.mjpeg' }] : []
    return { available: true, report_version: version, files }
  } })
  run.ui.confirmDeleteSelectedSdCardFiles()
  await run.ui.deleteSelectedDisplaySdCardFiles()
  assert.equal(run.ui.sdCardDeleteProgress.value.completed, 2)
  assert.equal(run.ui.sdCardDeleteProgress.value.state, 'complete')
  assert.equal(run.ui.displaySdCard.value.files.length, 0)
  assert.deepEqual(run.requests.map(request => request.method), ['DELETE', 'GET', 'DELETE', 'GET'])
  assert.ok(run.inventoryRequests.every(request => request.url === '/displays/one/display-sd-card'))
  assert.equal(run.ui.displaySdCard.value.inventory_refresh_pending, false)
})

for (const [label, report] of [
  ['stale', { available: true, report_version: 1, files: [] }],
  ['unavailable', { available: false, report_version: 2, files: [] }],
  ['missing files', { available: true, report_version: 2 }],
  ['malformed files', { available: true, report_version: 2, files: [null] }],
  ['synthetic pending inventory', { available: true, report_version: 2, files: [], inventory_refresh_pending: true }],
]) {
  test(`${label} inventory cannot turn an unconfirmed file into a successful deletion`, async () => {
    let inventoryReads = 0
    const run = setup({
      onPoll: (_ui, request) => request.url.endsWith('delete-1') ? 'complete' : 'pending',
      onInventory: ui => ++inventoryReads <= 2 ? { available: true, report_version: 1, files: ui.displaySdCard.value.files } : report,
    })
    run.ui.confirmDeleteSelectedSdCardFiles()
    await run.ui.deleteSelectedDisplaySdCardFiles()
    assert.equal(run.ui.sdCardDeleteProgress.value.completed, 1)
    assert.equal(run.ui.sdCardDeleteProgress.value.total, 2)
    assert.equal(run.ui.sdCardDeleteProgress.value.state, 'stopped')
    assert.equal(run.ui.sdCardDeleteProgress.value.filename, 'b.mjpeg')
    assert.match(run.ui.error.value, /Removed 1 of 2/)
    assert.match(run.ui.error.value, /may already have been removed/)
    assert.deepEqual(Array.from(run.ui.selectedSdCardFileNames.value), ['b.mjpeg'])
    assert.ok(run.elapsed >= 90000 && run.elapsed <= 90500)
    assert.equal(run.requests.filter(request => request.method === 'DELETE').length, 2)
  })
}

test('failed command stops with honest progress even if a newer inventory omits its filename', async () => {
  const run = setup({ status: 'failed', onInventory: () => ({ available: true, report_version: 10, files: [] }) })
  run.ui.confirmDeleteSelectedSdCardFiles()
  await run.ui.deleteSelectedDisplaySdCardFiles()
  assert.equal(run.ui.sdCardDeleteProgress.value.completed, 0)
  assert.equal(run.ui.sdCardDeleteProgress.value.state, 'stopped')
  assert.equal(run.requests.filter(request => request.method === 'DELETE').length, 1)
  assert.equal(run.ui.displaySdCard.value.files.length, 2)
})

test('the confirmation closes immediately and Stop after this file waits for the dispatched result', async () => {
  const reply = deferred()
  const run = setup({ onPoll: () => reply.promise })
  run.ui.confirmDeleteSelectedSdCardFiles()
  const deletion = run.ui.deleteSelectedDisplaySdCardFiles()
  while (!run.requests.some(request => request.method === 'GET')) await Promise.resolve()
  assert.equal(run.ui.deleteSdCardFilesDialog.value, false)
  assert.equal(run.ui.sdCardDeleteProgress.value.completed, 0)
  assert.equal(run.ui.sdCardDeleteProgress.value.filename, 'a.jpg')
  assert.equal(run.ui.displaySdCard.value.files.length, 2)
  run.ui.stopSdCardDeletionAfterCurrentFile()
  reply.resolve('complete')
  await deletion
  assert.equal(run.ui.sdCardDeleteProgress.value.completed, 1)
  assert.equal(run.ui.sdCardDeleteProgress.value.state, 'stopped')
  assert.deepEqual(Array.from(run.ui.selectedSdCardFileNames.value), ['b.mjpeg'])
  assert.equal(run.requests.filter(request => request.method === 'DELETE').length, 1)
})

test('switching displays during the pre-deletion inventory read stops before DELETE', async () => {
  const run = setup({ onInventory: current => { current.selectDisplay('two'); return { available: true, report_version: 1, files: [] } } })
  run.ui.confirmDeleteSelectedSdCardFiles()
  await run.ui.deleteSelectedDisplaySdCardFiles()
  assert.deepEqual(run.requests, [])
  assert.deepEqual(run.inventoryRequests.map(request => request.url), ['/displays/one/display-sd-card'])
  assert.match(run.ui.error.value, /Active display changed/)
})

for (const busyRef of ['sdCardInventoryRefreshing', 'savingToDisplaySdCard', 'savingVideoToDisplaySdCard', 'displayingSdCardFile', 'displayExperienceSaving', 'displayExperiencePreviewChanging', 'displayExperiencePreviewing']) {
  test(`${busyRef} blocks deletion while another display command is in flight`, () => {
    const run = setup()
    run.ui[busyRef].value = true
    run.ui.confirmDeleteSelectedSdCardFiles()
    assert.equal(run.ui.sdCardDeleteTarget.value, null)
    assert.match(run.ui.error.value, /current display operation/)
    assert.deepEqual(run.requests, [])
  })
}

test('the eight-file case recovers a physically deleted second file with a lost acknowledgement', async () => {
  let dispatched = ''
  let version = 1
  let physicalFiles
  const run = setup({
    onDelete: (_ui, request) => { dispatched = decodeURIComponent(request.url.split('/').at(-1)) },
    onInventory: () => ({ available: true, report_version: version, files: physicalFiles }),
    onPoll: (_ui, request) => {
      physicalFiles = physicalFiles.filter(file => file.name !== dispatched)
      ++version
      return request.url.endsWith('delete-2') ? 'pending' : 'complete'
    },
  })
  run.files.push(...Array.from({ length: 6 }, (_, index) => ({ name: `extra-${index}.jpg`, type: 'image' })))
  physicalFiles = run.files.map(file => ({ ...file }))
  run.ui.selectedSdCardFileNames.value = run.files.map(file => file.name)
  run.ui.confirmDeleteSelectedSdCardFiles()
  await run.ui.deleteSelectedDisplaySdCardFiles()
  assert.equal(run.ui.sdCardDeleteProgress.value.completed, 8)
  assert.equal(run.ui.sdCardDeleteProgress.value.total, 8)
  assert.equal(run.ui.sdCardDeleteProgress.value.state, 'complete')
  assert.equal(run.requests.filter(request => request.method === 'DELETE').length, 8)
  assert.equal(run.ui.displaySdCard.value.files.length, 0)
  assert.equal(run.ui.error.value, '')
})

test('periodic inventory loads pause only for the original deleting display', async () => {
  const reply = deferred()
  const run = setup({ onPoll: () => reply.promise })
  let reports = 0
  run.ui.fetchDisplaySdCardReport = async () => {
    ++reports
    return { available: true, report_version: 2, files: [{ name: 'other.jpg' }] }
  }
  const loadCode = source.slice(source.indexOf('async function loadDisplaySdCard()'), source.indexOf('async function refreshDisplaySdCardInventory()'))
  vm.runInContext(loadCode, run.ui)
  run.ui.confirmDeleteSelectedSdCardFiles()
  const deletion = run.ui.deleteSelectedDisplaySdCardFiles()
  while (!run.requests.some(request => request.method === 'GET')) await Promise.resolve()
  await run.ui.loadDisplaySdCard()
  assert.equal(reports, 0)
  assert.equal(run.ui.displaySdCard.value.files.length, 2)
  run.ui.selectDisplay('two')
  await run.ui.loadDisplaySdCard()
  assert.ok(reports > 0)
  assert.equal(run.ui.displaySdCardScope.value, '/displays/two')
  assert.equal(run.ui.displaySdCard.value.files[0].name, 'other.jpg')
  reply.resolve('complete')
  await deletion
  assert.equal(run.ui.displaySdCard.value.files[0].name, 'other.jpg')
})

test('refresh, playback, and navigation stop-preview cannot replace a pending deletion', async () => {
  const run = setup()
  run.ui.deletingSdCardFiles.value = true
  const refreshCode = source.slice(source.indexOf('async function refreshDisplaySdCardInventory()'), source.indexOf('async function refreshDisplaySdCard()'))
  const playbackCode = source.slice(source.indexOf('async function showSDCardFileOnDisplay('), source.indexOf('async function loadAppSettings()'))
  const stopPreviewCode = source.slice(source.indexOf('async function stopDisplayExperiencePreview('), source.indexOf('async function sendDisplaySdCardCommand('))
  run.ui.status = { value: '' }
  vm.runInContext(refreshCode + '\n' + playbackCode + '\n' + stopPreviewCode, run.ui)
  await assert.rejects(run.ui.refreshDisplaySdCardInventory(), /current SD-card deletion/)
  assert.equal(await run.ui.showSDCardFileOnDisplay('a.jpg'), false)
  assert.match(run.ui.error.value, /current SD-card deletion/)
  run.ui.displayExperiencePreviewing.value = true
  await run.ui.stopDisplayExperiencePreview()
  assert.deepEqual(run.requests, [])
  assert.deepEqual(run.inventoryRequests, [])
})

test('a missing command ID stops without polling or sending another deletion', async () => {
  const run = setup()
  const fetch = run.ui.fetch
  run.ui.fetch = async (url, options) => {
    const response = await fetch(url, options)
    return options?.method === 'DELETE' ? { ok: true, json: async () => ({ id: '' }) } : response
  }
  run.ui.confirmDeleteSelectedSdCardFiles()
  await run.ui.deleteSelectedDisplaySdCardFiles()
  assert.deepEqual(run.requests.map(request => request.method), ['DELETE'])
  assert.equal(run.ui.sdCardDeleteProgress.value.completed, 0)
  assert.equal(run.ui.sdCardDeleteProgress.value.state, 'stopped')
  assert.match(run.ui.error.value, /did not return a deletion request/)
})
