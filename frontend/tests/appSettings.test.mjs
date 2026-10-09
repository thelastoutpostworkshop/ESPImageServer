import test from 'node:test'
import assert from 'node:assert/strict'
import { createAppSettingsSaver } from '../src/appSettings.js'

function deferred() {
  let resolve, reject
  const promise = new Promise((yes, no) => { resolve = yes; reject = no })
  return { promise, resolve, reject }
}

test('a setting saves immediately as a partial patch', async () => {
  const writes = [], states = []
  const saver = createAppSettingsSaver({
    request: async patch => { writes.push(patch); return { jpeg_quality: patch.jpeg_quality } },
    onState: state => states.push(state),
  })
  const saved = saver.save({ jpeg_quality: 75 })
  assert.deepEqual(writes, [{ jpeg_quality: 75 }])
  assert.equal(states[0].saving, true)
  assert.deepEqual(await saved, { jpeg_quality: 75 })
  assert.deepEqual(states.at(-1), { saving: false, error: null, saved: true })
})

test('rapid changes share the next write and cannot overlap the current save', async () => {
  const first = deferred(), second = deferred(), writes = [], states = []
  let active = 0
  const saver = createAppSettingsSaver({
    request: async patch => {
      assert.equal(++active, 1, 'Settings writes must not overlap')
      writes.push(patch)
      try { return await (writes.length === 1 ? first.promise : second.promise) }
      finally { --active }
    },
    onState: state => states.push(state),
  })
  const original = saver.save({ jpeg_quality: 70 })
  const next = saver.save({ jpeg_quality: 75 })
  const latest = saver.save({ jpeg_quality: 80, confirm_deletion: false })
  const video = saver.save({ video_jpeg_quality: 17 })
  assert.deepEqual(writes, [{ jpeg_quality: 70 }])
  first.resolve({ jpeg_quality: 70 })
  assert.deepEqual(await original, { jpeg_quality: 70 })
  assert.deepEqual(writes[1], { jpeg_quality: 80, confirm_deletion: false, video_jpeg_quality: 17 })
  assert.equal(states.at(-1).saving, true)
  second.resolve({ jpeg_quality: 80, confirm_deletion: false, video_jpeg_quality: 17 })
  const results = await Promise.all([next, latest, video])
  assert.ok(results.every(result => result.jpeg_quality === 80))
  assert.equal(states.at(-1).saving, false)
  assert.equal(states.at(-1).saved, true)
})

test('failed writes reject their callers while later pending changes still save', async () => {
  const first = deferred(), writes = [], states = []
  const saver = createAppSettingsSaver({
    request: patch => {
      writes.push(patch)
      return writes.length === 1 ? first.promise : Promise.resolve(patch)
    },
    onState: state => states.push(state),
  })
  const failed = saver.save({ jpeg_quality: 75 })
  const failureCheck = assert.rejects(failed, /Connection lost/)
  const later = saver.save({ video_jpeg_quality: 17 })
  first.reject(new Error('Connection lost'))
  await failureCheck
  assert.deepEqual(await later, { video_jpeg_quality: 17 })
  assert.equal(states.at(-1).saving, false)
  assert.match(states.at(-1).error.message, /Connection lost/)
  assert.equal(states.at(-1).saved, false)
  assert.deepEqual(await saver.save({ jpeg_quality: 80 }), { jpeg_quality: 80 })
  assert.deepEqual(states.at(-1), { saving: false, error: null, saved: true })
})

test('empty changes do not write or report a save', async () => {
  const saver = createAppSettingsSaver({
    request: () => assert.fail('No settings were changed'),
    onState: () => assert.fail('No save was started'),
  })
  assert.equal(await saver.save({}), null)
})
