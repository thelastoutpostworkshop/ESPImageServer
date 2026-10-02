import test from 'node:test'
import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import vm from 'node:vm'
import { sdSaveCommandEndpoint } from '../src/sdSaveProgress.js'

const source = await readFile(new URL('../src/App.vue', import.meta.url), 'utf8')
const deletionCode = source.slice(source.indexOf('function displaySdCardMediaType('), source.indexOf('async function showSDCardFileOnDisplay('))
const selectionWatcherCode = source.slice(source.indexOf('watch(activeDisplayId,'), source.indexOf('const displayMessage = computed('))

function deferred() {
  let resolve
  const promise = new Promise(complete => { resolve = complete })
  return { promise, resolve }
}

// Execute the real confirmation, deletion, and selection-change functions with
// controlled network awaits. No actual device receives a deletion command.
function setup({ status = 'complete', onPreferenceSave, onDelete, onPoll, legacy = false } = {}) {
  let scope = legacy ? '' : '/displays/one'
  let selectionWatcher
  let commandCount = 0
  const requests = []
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
    sdCardLoadSequence: 0,
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
      requests.push(request)
      if (request.method === 'DELETE') {
        const command = {
          id: `delete-${++commandCount}`,
          display_id: url.startsWith('/displays/') ? decodeURIComponent(url.split('/')[2]) : '__legacy__',
        }
        await onDelete?.(ui, request)
        return { ok: true, json: async () => command }
      }
      const pollStatus = await onPoll?.(ui, request) || status
      return { ok: true, json: async () => ({ status: pollStatus, detail: pollStatus === 'complete' ? 'Deleted' : 'Could not delete' }) }
    },
  })
  vm.runInContext(deletionCode + '\n' + selectionWatcherCode, ui)
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
  return { ui, files, requests, notifications, loads }
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
