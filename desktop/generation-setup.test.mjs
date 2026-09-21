import test from 'node:test'
import assert from 'node:assert/strict'
import { EventEmitter } from 'node:events'
import { GenerationSetup } from './generation-setup.mjs'

function fixture() {
  const child = new EventEmitter()
  child.stdout = new EventEmitter(); child.stderr = new EventEmitter()
  const status = [], logs = [], calls = []
  const setup = new GenerationSetup({ spawnProcess: (...args) => { calls.push(args); return child },
    onStatus: (...args) => status.push(args), onLog: line => logs.push(line) })
  return { setup, child, status, logs, calls }
}
test('setup streams progress and accepts a verified runtime only after process exit', async () => {
  const { setup, child, status, calls } = fixture()
  const promise = setup.start({ pythonPath: '/base/python', projectRoot: '/app' }, '/user/runtime')
  assert.throws(() => setup.start({}, ''), /already running/)
  child.stdout.emit('data', '{"kind":"status","title":"Downloading",')
  child.stdout.emit('data', '"detail":"torch"}\n{"kind":"ready","python":"/user/python"}\n')
  child.emit('close', 0)
  assert.equal((await promise).python, '/user/python')
  assert.deepEqual(status, [['Downloading', 'torch']])
  assert.equal(calls[0][2].detached, true)
})
test('unsupported GPU is distinguishable from a failed installation', async () => {
  const { setup, child } = fixture()
  const promise = setup.start({ pythonPath: '/base/python', projectRoot: '/app' }, '/user')
  child.stdout.emit('data', '{"kind":"unsupported","detail":"NVIDIA missing"}\n'); child.emit('close', 0)
  assert.equal((await promise).kind, 'unsupported')
  const failed = setup.start({ pythonPath: '/base/python', projectRoot: '/app' }, '/user')
  child.stdout.emit('data', '{"kind":"error","detail":"Network unavailable"}\n'); child.emit('close', 1)
  await assert.rejects(failed, /Network unavailable/)
})

test('quitting terminates the setup process group and waits for completion', async () => {
  const child = new EventEmitter()
  child.pid = 42; child.stdout = new EventEmitter(); child.stderr = new EventEmitter()
  const signals = []
  const setup = new GenerationSetup({ spawnProcess: () => child, signalGroup: (pid, signal) => {
    signals.push([pid, signal]); child.emit('close', null)
  } })
  const completion = setup.start({ pythonPath: '/base/python', projectRoot: '/app' }, '/user')
  const rejected = assert.rejects(completion, /stopped before/)
  await setup.stop()
  await rejected
  assert.deepEqual(signals, [[42, 'SIGTERM']])
  assert.equal(setup.child, null)
})
