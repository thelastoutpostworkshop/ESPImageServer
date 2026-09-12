import test from 'node:test'
import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import vm from 'node:vm'
import { sdSaveProgressMessage, sdSaveCommandEndpoint } from '../src/sdSaveProgress.js'

test('download completion remains distinct from committed save', () => {
  assert.equal(sdSaveProgressMessage({ progress: { stage: 'downloading', received_bytes: 50, total_bytes: 100 } }), 'Saving to SD card: 50% received…')
  assert.match(sdSaveProgressMessage({ progress: { stage: 'downloading', received_bytes: 100, total_bytes: 100 } }), /100% received/)
  assert.match(sdSaveProgressMessage({ progress: { stage: 'verifying' } }), /Checking the file/)
  assert.equal(sdSaveProgressMessage({}), '')
})
test('cancel request is not confirmation and superseded saves are distinct', () => {
  assert.match(sdSaveProgressMessage({ status: 'cancelling' }), /waiting for the display/)
  assert.equal(sdSaveProgressMessage({ status: 'cancelled' }), 'Save cancelled.')
  assert.match(sdSaveProgressMessage({ status: 'superseded' }), /replaced/)
})
test('polling and cancellation remain bound to the command display', () => {
  assert.equal(sdSaveCommandEndpoint({ id: 'save/1', display_id: 'screen A' }), '/displays/screen%20A/display-commands/save%2F1')
  assert.equal(sdSaveCommandEndpoint({ id: 'save1', display_id: '__legacy__' }), '/display-commands/save1')
})
test('invalid totals do not show NaN or an unbounded percentage', () => {
  assert.match(sdSaveProgressMessage({ progress: { received_bytes: 1, total_bytes: 0 } }), /Waiting/)
  assert.match(sdSaveProgressMessage({ progress: { received_bytes: 200, total_bytes: 100 } }), /100%/)
})

// Exercise the real refresh preflight, with selection changing at an await.
// No Vue DOM or device commands are needed to reproduce this race.
const appSource = await readFile(new URL('../src/App.vue', import.meta.url), 'utf8')
const refreshFunction = appSource.slice(appSource.indexOf('async function refreshDisplaySdCardInventory()'), appSource.indexOf('async function refreshDisplaySdCard()'))
for (const switchAt of ['initial inventory', 'command polling']) {
  test(`changing displays during ${switchAt} never redirects the save preflight`, async () => {
    let selected = '/displays/original'
    const requests = []
    const context = {
      activeDisplayOnline: { value: true }, displaySdCardLoading: { value: false }, displaySdCard: { value: {} },
      selectedDisplayEndpoint: suffix => selected + suffix,
      sdSaveCommandEndpoint,
      fetchDisplaySdCardReport: async () => { if (switchAt === 'initial inventory') selected = '/displays/other'; return { report_version: 1 } },
      fetch: async url => { requests.push(url); return { ok: true, json: async () => ({ id: 'refresh', display_id: 'original' }) } },
      window: { setTimeout: callback => { selected = '/displays/other'; callback() } },
    }
    const refresh = vm.runInNewContext(`(${refreshFunction.trim()})`, context)
    await assert.rejects(refresh(), /Active display changed/)
    assert.deepEqual(requests, switchAt === 'initial inventory' ? [] : ['/displays/original/display-sd-card/refresh'])
    assert.equal(context.displaySdCardLoading.value, false)
  })
}
