import test from 'node:test'
import assert from 'node:assert/strict'
import { createSdSaveCloseGuard, sdSaveCloseDialog } from './sd-save-close.mjs'

function deferred() {
  let resolve
  const promise = new Promise(yes => { resolve = yes })
  return { promise, resolve }
}

const tick = () => new Promise(resolve => setImmediate(resolve))

for (const status of ['queued', 'running', 'cancelling']) {
  test(`${status} SD-card saves cannot be overridden by closing the warning`, async () => {
    const save = { display_id: 'one', display_name: 'Display one', status }
    const notifications = []
    const guard = createSdSaveCloseGuard({
      readSaves: async () => [save],
      notify: async state => { notifications.push(state); return true },
    })
    assert.equal(await guard.request(), false)
    assert.deepEqual(notifications, [{ saves: [save], unknown: false }])
    assert.equal(save.status, status)
    assert.equal(guard.pending, false)
  })
}

test('active saves on every display are retained in the warning state', async () => {
  const saves = [{ display_id: 'inactive', status: 'running' }, { display_id: 'active', status: 'cancelling' }]
  const guard = createSdSaveCloseGuard({
    readSaves: async () => saves,
    notify: async state => { assert.deepEqual(state, { saves, unknown: false }) },
  })
  assert.equal(await guard.request(), false)
})

test('a nonempty object snapshot is blocked even when descriptive fields are absent', async () => {
  const guard = createSdSaveCloseGuard({
    readSaves: async () => [{}],
    notify: async state => { assert.equal(state.unknown, false); assert.equal(state.saves.length, 1) },
  })
  assert.equal(await guard.request(), false)
})

test('idle checks are fresh rather than granting cached approval', async () => {
  let saves = [], checks = 0, warnings = 0
  const guard = createSdSaveCloseGuard({
    readSaves: async () => { checks += 1; return saves },
    notify: async () => { warnings += 1 },
  })
  assert.equal(await guard.request(), true)
  saves = [{ status: 'running' }]
  assert.equal(await guard.request(), false)
  saves = []
  assert.equal(await guard.request(), true)
  assert.equal(checks, 3)
  assert.equal(warnings, 1)
})

for (const [reason, readSaves] of [
  ['unavailable server', async () => { throw new Error('Connection failed') }],
  ['non-array response', async () => ({ sd_card_saves: [] })],
  ['null entry', async () => [null]],
  ['array entry', async () => [[]]],
  ['primitive entry', async () => ['running']],
]) {
  test(`${reason} keeps the application open because SD-card work is unknown`, async () => {
    const notifications = []
    const guard = createSdSaveCloseGuard({ readSaves, notify: async state => { notifications.push(state) } })
    assert.equal(await guard.request(), false)
    assert.equal(notifications.length, 1)
    assert.equal(notifications[0].unknown, true)
    assert.equal(guard.pending, false)
  })
}

test('parallel close requests share a read and warning until it is dismissed', async () => {
  const snapshot = deferred(), warning = deferred()
  let checks = 0, notifications = 0
  const guard = createSdSaveCloseGuard({
    readSaves: () => { checks += 1; return snapshot.promise },
    notify: () => { notifications += 1; return warning.promise },
  })
  const first = guard.request(), second = guard.request()
  assert.equal(first, second)
  assert.equal(guard.pending, true)
  snapshot.resolve([{ status: 'running' }])
  await tick()
  assert.equal(guard.request(), first)
  assert.equal(checks, 1)
  assert.equal(notifications, 1)
  warning.resolve()
  assert.deepEqual(await Promise.all([first, second]), [false, false])
  assert.equal(guard.pending, false)
})

test('a notification failure keeps the app open and releases a later retry', async () => {
  let saves = [{ status: 'running' }]
  const errors = []
  const guard = createSdSaveCloseGuard({
    readSaves: async () => saves,
    notify: async () => { throw new Error('Dialog unavailable') },
    onError: error => { errors.push(error.message) },
  })
  assert.equal(await guard.request(), false)
  assert.equal(guard.pending, false)
  assert.deepEqual(errors, ['Dialog unavailable'])
  saves = []
  assert.equal(await guard.request(), true)
})

test('SD-card dialogs offer only Keep open and explain the cancellation acknowledgement', () => {
  for (const unknown of [false, true]) {
    const dialog = sdSaveCloseDialog({ unknown })
    assert.deepEqual(dialog.buttons, ['Keep open'])
    assert.equal(dialog.defaultId, 0)
    assert.equal(dialog.cancelId, 0)
    assert.equal(dialog.noLink, true)
    assert.doesNotMatch(dialog.detail, /close anyway|override|continue in the background/i)
  }
  const active = sdSaveCloseDialog({ saves: [{ status: 'cancelling' }] })
  assert.match(active.detail, /cancel.*in the app/i)
  assert.match(active.detail, /display to confirm cancellation/i)
  assert.match(sdSaveCloseDialog({ unknown: true }).message, /could not.*check|could not.*confirm/i)
})
