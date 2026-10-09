import test from 'node:test'
import assert from 'node:assert/strict'
import { createGenerationCloseGuard, generationCloseDialog } from './generation-close.mjs'

function deferred() {
  let resolve, reject
  const promise = new Promise((yes, no) => { resolve = yes; reject = no })
  return { promise, resolve, reject }
}

for (const kind of ['image', 'video']) {
  for (const status of ['running', 'queued', 'cancelling']) {
    test(`${kind} ${status} requires confirmation and Keep open leaves work running`, async () => {
      const job = { id: 'job', kind, status, stage: 'Loading model' }
      const guard = createGenerationCloseGuard({
        readJobs: async () => [job, { kind, status: 'complete' }],
        confirm: async value => { assert.deepEqual(value, { jobs: [job], unknown: false }); return false },
      })
      assert.equal(await guard.request(), false)
      assert.equal(guard.approved, false)
      assert.equal(guard.pending, false)
      assert.equal(job.status, status)
    })
  }
}

test('idle and finished queues close without prompting', async () => {
  for (const jobs of [[], ['complete', 'failed', 'cancelled'].map(status => ({ kind: 'image', status }))]) {
    const guard = createGenerationCloseGuard({ readJobs: async () => jobs, confirm: assert.fail })
    assert.equal(await guard.request(), true)
    assert.equal(guard.approved, true)
  }
})

test('repeated close and quit events share one asynchronous check and confirmation', async () => {
  const queue = deferred(), answer = deferred()
  let checks = 0, confirmations = 0
  const guard = createGenerationCloseGuard({
    readJobs: () => { checks += 1; return queue.promise },
    confirm: () => { confirmations += 1; return answer.promise },
  })
  const first = guard.request(), second = guard.request()
  assert.equal(first, second)
  assert.equal(guard.pending, true)
  queue.resolve([{ kind: 'video', status: 'running' }])
  await new Promise(resolve => setImmediate(resolve))
  assert.equal(guard.request(), first)
  answer.resolve(true)
  assert.deepEqual(await Promise.all([first, second]), [true, true])
  assert.equal(await guard.request(), true)
  assert.equal(checks, 1)
  assert.equal(confirmations, 1)
})

test('declining close lets a later attempt check fresh generation state', async () => {
  let jobs = [{ status: 'running', kind: 'image' }], confirmations = 0
  const guard = createGenerationCloseGuard({
    readJobs: async () => jobs,
    confirm: async () => { confirmations += 1; return false },
  })
  assert.equal(await guard.request(), false)
  jobs = [{ status: 'complete', kind: 'image' }]
  assert.equal(await guard.request(), true)
  assert.equal(confirmations, 1)
})

test('reset checks again after a window-only close and revokes pending approval', async () => {
  let checks = 0
  const answer = deferred()
  const guard = createGenerationCloseGuard({
    readJobs: async () => { checks += 1; return [{ status: 'running', kind: 'image' }] },
    confirm: () => answer.promise,
  })
  const pending = guard.request()
  await new Promise(resolve => setImmediate(resolve))
  guard.reset()
  answer.resolve(true)
  assert.equal(await pending, false)
  assert.equal(guard.approved, false)
  assert.equal(await guard.request(), true)
  guard.reset()
  assert.equal(await guard.request(), true)
  assert.equal(checks, 3)
})

for (const readJobs of [async () => { throw new Error('Timed out') }, async () => ({ status: 'running' })]) {
  test('an unavailable or invalid queue requires an explicit decision', async () => {
    const guard = createGenerationCloseGuard({
      readJobs,
      confirm: async state => { assert.equal(state.unknown, true); return false },
    })
    assert.equal(await guard.request(), false)
    assert.equal(guard.approved, false)
  })
}

test('a dialog failure keeps the app open and permits a later retry', async () => {
  const errors = []
  let broken = true
  const guard = createGenerationCloseGuard({
    readJobs: async () => [{ status: 'running', kind: 'video' }],
    confirm: async () => { if (broken) throw new Error('Dialog unavailable'); return true },
    onError: error => errors.push(error.message),
  })
  assert.equal(await guard.request(), false)
  assert.deepEqual(errors, ['Dialog unavailable'])
  broken = false
  assert.equal(await guard.request(), true)
})

test('close dialogs default to Keep open and describe server ownership accurately', () => {
  const owned = generationCloseDialog()
  assert.deepEqual(owned.buttons, ['Keep open', 'Close anyway'])
  assert.equal(owned.defaultId, 0)
  assert.equal(owned.cancelId, 0)
  assert.match(owned.detail, /will stop unfinished generation/)
  assert.match(generationCloseDialog({ unknown: true }).detail, /may stop/)
  const continuing = generationCloseDialog({ stopsGeneration: false })
  assert.match(continuing.detail, /continue in the background/)
  assert.match(continuing.detail, /close the application/)
  assert.doesNotMatch(continuing.detail, /stop|discard/)
  assert.match(generationCloseDialog({ stopsGeneration: false, closesApplication: false }).detail, /close the window/)
})
