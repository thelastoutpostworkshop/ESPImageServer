import test from 'node:test'
import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import vm from 'node:vm'
const source = await readFile(new URL('../src/App.vue', import.meta.url), 'utf8')
const code = source.slice(source.indexOf('async function deleteSdCardFileAndWait('), source.indexOf('async function deleteSelectedDisplaySdCardFiles('))
function setup(status, switchDisplay = false) {
  let scope = '/displays/one'
  let calls = 0
  const context = vm.createContext({
    activeDisplayOnline: { value: true },
    activeDisplayCommandUnavailableMessage: () => 'Offline',
    selectedDisplayEndpoint: path => scope + path,
    sdSaveCommandEndpoint: command => `/displays/${command.display_id}/display-commands/${command.id}`,
    sdCardLoadSequence: 0, displaySdCardLoading: { value: true },
    displaySdCard: { value: { files: [{ name: 'a.jpg' }, { name: 'b.mjpeg' }] } },
    selectedSdCardFileNames: { value: ['a.jpg'] },
    window: { setTimeout: callback => callback() },
    fetch: async () => {
      calls++
      if (calls === 2 && switchDisplay) scope = '/displays/two'
      return { ok: true, json: async () => calls === 1 ? { id: 'command', display_id: 'one' } : { status } }
    },
  })
  vm.runInContext('function displaySdCardFiles() { return displaySdCard.value.files }\n' + code, context)
  return context
}
test('confirmed deletion immediately removes file and invalidates older loads', async () => {
  const ui = setup('complete')
  await ui.deleteSdCardFileAndWait({ name: 'a.jpg' })
  assert.equal(ui.displaySdCard.value.files.length, 1)
  assert.equal(ui.displaySdCard.value.files[0].name, 'b.mjpeg')
  assert.equal(ui.displaySdCard.value.inventory_refresh_pending, true)
  assert.equal(ui.sdCardLoadSequence, 1)
})
for (const status of ['failed', 'superseded', 'cancelled']) {
  test(`${status} deletion keeps file visible`, async () => {
    const ui = setup(status)
    await assert.rejects(ui.deleteSdCardFileAndWait({ name: 'a.jpg' }))
    assert.equal(ui.displaySdCard.value.files.length, 2)
  })
}
test('switching displays cannot remove a file from the new selection', async () => {
  const ui = setup('complete', true)
  await assert.rejects(ui.deleteSdCardFileAndWait({ name: 'a.jpg' }), /Active display changed/)
  assert.equal(ui.displaySdCard.value.files.length, 2)
})
