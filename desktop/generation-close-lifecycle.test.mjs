import test from 'node:test'
import assert from 'node:assert/strict'
import { EventEmitter } from 'node:events'
import { readFile } from 'node:fs/promises'
import vm from 'node:vm'
import { createGenerationCloseGuard, generationCloseDialog } from './generation-close.mjs'

const source = await readFile(new URL('./main.mjs', import.meta.url), 'utf8')

function slice(start, end) {
  const from = source.indexOf(start), to = source.indexOf(end, from + start.length)
  assert.ok(from >= 0 && to > from, `Missing production boundary: ${start} / ${end}`)
  return source.slice(from, to)
}

function deferred() {
  let resolve
  const promise = new Promise(yes => { resolve = yes })
  return { promise, resolve }
}

const tick = () => new Promise(resolve => setImmediate(resolve))
async function settle() { await tick(); await tick() }
function event() {
  return { prevented: false, preventDefault() { this.prevented = true } }
}

// Run the actual main-process guard and event hooks with native dependencies
// replaced by fixtures. No Electron windows, server, or USB device are opened.
function setup(options = {}) {
  const app = new EventEmitter(), window = new EventEmitter()
  const dialogs = [], firmwareWarnings = [], lifecycle = [], warnings = []
  let destroyed = false, closingByApp = false, checks = 0, windowCloseCalls = 0, quitCalls = 0
  const serverRuntime = {
    child: options.owned === false ? null : { pid: 123 },
    stop: async () => { lifecycle.push('server-stop'); serverRuntime.child = null },
  }
  const firmwareInstaller = { state: { busy: false } }
  const wifiSetup = { running: false, completion: Promise.resolve(), cancel: () => lifecycle.push('wifi-cancel') }
  window.isDestroyed = () => destroyed
  window.close = () => {
    windowCloseCalls += 1
    const closing = event()
    window.emit('close', closing)
    if (!closing.prevented && !destroyed) {
      destroyed = true
      window.emit('closed')
      if (!closingByApp && options.platform !== 'darwin') app.quit()
    }
    return closing
  }
  app.quit = () => {
    quitCalls += 1
    const quitting = event()
    app.emit('before-quit', quitting)
    if (!quitting.prevented) {
      lifecycle.push('app-quit')
      closingByApp = true
      if (!destroyed) window.close()
      closingByApp = false
    }
    return quitting
  }
  const ui = vm.createContext({
    app, window, serverRuntime, firmwareInstaller, wifiSetup,
    createGenerationCloseGuard, generationCloseDialog, AbortSignal,
    process: { platform: options.platform || 'win32' },
    dialog: {
      showMessageBox: async (...args) => {
        dialogs.push(args.at(-1))
        return options.confirm ? options.confirm(dialogs.length) : { response: 1 }
      },
      showMessageBoxSync: (_window, settings) => firmwareWarnings.push(settings),
    },
    fetch: async url => {
      assert.equal(url, 'http://127.0.0.1:8000/generation-queue')
      checks += 1
      const jobs = options.readJobs ? await options.readJobs(checks)
        : options.jobs || [{ kind: 'image', status: 'running' }]
      return { ok: true, json: async () => jobs }
    },
    generationSetup: { stop: async () => { lifecycle.push('setup-stop') } },
    saveWindowState: () => lifecycle.push('save-window'),
    clearTimeout: () => {},
    console: { warn: (...args) => warnings.push(args) },
  })
  const beforeQuitStart = source.indexOf('  let shutdownComplete = false')
  const beforeQuitEnd = source.indexOf('\n  })', beforeQuitStart) + '\n  })'.length
  assert.ok(beforeQuitStart >= 0 && beforeQuitEnd > beforeQuitStart)
  vm.runInContext([
    `let mainWindow = window; let closeAttempt = null; let isQuitting = false;
     let workspaceReady = ${options.ready !== false}; let setupChoice; let saveWindowStateTimer;`,
    slice('const stopsGenerationOnClose =', 'let setupChoice'),
    slice("window.on('closed', () => {", '  if (savedPositionIsVisible(windowState))'),
    slice("mainWindow.on('close', event => {", '  await window.loadFile('),
    source.slice(beforeQuitStart, beforeQuitEnd),
    'state = () => ({ isQuitting, closeAttempt, mainWindow, approved: generationCloseGuard.approved })',
  ].join('\n'), ui)
  return {
    app, window, ui, serverRuntime, firmwareInstaller, wifiSetup,
    dialogs, firmwareWarnings, lifecycle, warnings,
    checks: () => checks, closeCalls: () => windowCloseCalls, quitCalls: () => quitCalls,
  }
}

for (const action of ['close', 'quit']) {
  test(`${action} synchronously prevents exit while its generation check is pending`, async () => {
    const queue = deferred()
    const run = setup({ readJobs: () => queue.promise, confirm: () => ({ response: 0 }) })
    const initial = action === 'close' ? run.window.close() : run.app.quit()
    assert.equal(initial.prevented, true)
    assert.equal(run.ui.state().isQuitting, false)
    assert.equal(run.checks(), 0)
    assert.deepEqual(run.lifecycle, [])
    queue.resolve([{ status: 'running' }])
    await settle()
    assert.equal(run.dialogs.length, 1)
    assert.equal(run.window.isDestroyed(), false)
    assert.equal(run.ui.state().isQuitting, false)
    assert.equal(run.ui.state().closeAttempt, null)
    assert.deepEqual(run.lifecycle, [])
  })
}

test('repeated window close and quit requests share one dialog and retry cleanly after Keep open', async () => {
  const first = deferred(), second = deferred()
  const run = setup({ confirm: count => count === 1 ? first.promise : second.promise })
  run.window.close()
  await settle()
  run.window.close()
  run.app.quit()
  assert.equal(run.dialogs.length, 1)
  assert.equal(run.checks(), 1)
  first.resolve({ response: 0 })
  await settle()
  assert.deepEqual(run.lifecycle, [])
  assert.equal(run.window.isDestroyed(), false)
  run.window.close()
  await settle()
  assert.equal(run.dialogs.length, 2)
  second.resolve({ response: 1 })
  await settle()
  assert.equal(run.dialogs.length, 2)
  assert.equal(run.window.isDestroyed(), true)
  assert.equal(run.lifecycle.filter(item => item === 'server-stop').length, 1)
  assert.equal(run.lifecycle.filter(item => item === 'setup-stop').length, 1)
  assert.deepEqual(run.warnings, [])
})

test('simultaneous approved close and quit proceed with one prompt and one shutdown', async () => {
  const decision = deferred()
  const run = setup({ confirm: () => decision.promise })
  run.window.close()
  await settle()
  run.app.quit()
  run.window.close()
  decision.resolve({ response: 1 })
  await settle()
  assert.equal(run.dialogs.length, 1)
  assert.equal(run.checks(), 1)
  assert.equal(run.lifecycle.filter(item => item === 'server-stop').length, 1)
  assert.equal(run.lifecycle.filter(item => item === 'app-quit').length, 1)
  assert.equal(run.window.isDestroyed(), true)
})

test('an idle queue closes without prompting and still shuts down once', async () => {
  const run = setup({ jobs: [{ status: 'complete' }, { status: 'cancelled' }] })
  const initial = run.window.close()
  assert.equal(initial.prevented, true)
  await settle()
  assert.equal(run.dialogs.length, 0)
  assert.equal(run.checks(), 1)
  assert.equal(run.window.isDestroyed(), true)
  assert.equal(run.lifecycle.filter(item => item === 'server-stop').length, 1)
})

test('existing USB protection prevents both close and quit without checking generation', async () => {
  const run = setup()
  run.firmwareInstaller.state.busy = true
  assert.equal(run.window.close().prevented, true)
  assert.equal(run.app.quit().prevented, true)
  await settle()
  assert.equal(run.firmwareWarnings.length, 1)
  assert.equal(run.checks(), 0)
  assert.equal(run.dialogs.length, 0)
  assert.equal(run.window.isDestroyed(), false)
  assert.deepEqual(run.lifecycle, [])
})

test('USB work beginning during confirmation blocks closure and resets its approval', async () => {
  const first = deferred(), second = deferred()
  const run = setup({ confirm: count => count === 1 ? first.promise : second.promise })
  run.window.close()
  await settle()
  run.firmwareInstaller.state.busy = true
  first.resolve({ response: 1 })
  await settle()
  assert.equal(run.firmwareWarnings.length, 1)
  assert.equal(run.window.isDestroyed(), false)
  assert.equal(run.ui.state().approved, false)
  assert.deepEqual(run.lifecycle, [])
  run.firmwareInstaller.state.busy = false
  run.window.close()
  await settle()
  assert.equal(run.dialogs.length, 2)
  second.resolve({ response: 0 })
  await settle()
  assert.equal(run.window.isDestroyed(), false)
  assert.deepEqual(run.lifecycle, [])
})

test('macOS window-only confirmation resets after closure and a later Quit checks again', async () => {
  const run = setup({ platform: 'darwin' })
  run.window.close()
  await settle()
  assert.equal(run.window.isDestroyed(), true)
  assert.match(run.dialogs[0].detail, /continue in the background/)
  assert.equal(run.ui.state().approved, false)
  assert.equal(run.ui.state().mainWindow, undefined)
  assert.equal(run.serverRuntime.child.pid, 123)
  assert.equal(run.lifecycle.filter(item => item === 'server-stop').length, 0)
  run.app.quit()
  await settle()
  assert.equal(run.dialogs.length, 2)
  assert.match(run.dialogs[1].detail, /stop unfinished generation/)
  assert.equal(run.lifecycle.filter(item => item === 'server-stop').length, 1)
})

test('macOS Quit joining a window-only prompt requires confirmation of stopping generation', async () => {
  const windowDecision = deferred(), quitDecision = deferred()
  const run = setup({ platform: 'darwin', confirm: count => count === 1 ? windowDecision.promise : quitDecision.promise })
  run.window.close()
  await settle()
  assert.match(run.dialogs[0].detail, /continue in the background/)
  run.app.quit()
  windowDecision.resolve({ response: 1 })
  await settle()
  assert.equal(run.dialogs.length, 2)
  assert.match(run.dialogs[1].detail, /stop unfinished generation/)
  assert.equal(run.window.isDestroyed(), false)
  assert.equal(run.ui.state().isQuitting, false)
  assert.deepEqual(run.lifecycle, [])
  quitDecision.resolve({ response: 0 })
  await settle()
  assert.equal(run.window.isDestroyed(), false)
  assert.deepEqual(run.lifecycle, [])
})

test('approved Quit cancels Wi-Fi and waits for USB completion before stopping the server', async () => {
  const decision = deferred(), completion = deferred()
  const run = setup({ confirm: () => decision.promise })
  run.wifiSetup.running = true
  run.wifiSetup.completion = completion.promise
  run.firmwareInstaller.state.busy = true
  run.app.quit()
  await settle()
  assert.equal(run.dialogs.length, 1)
  assert.deepEqual(run.lifecycle, [])
  decision.resolve({ response: 1 })
  await settle()
  assert.deepEqual(run.lifecycle, ['wifi-cancel'])
  assert.equal(run.window.isDestroyed(), false)
  run.wifiSetup.running = false
  run.firmwareInstaller.state.busy = false
  completion.resolve()
  await settle()
  assert.equal(run.window.isDestroyed(), true)
  assert.equal(run.dialogs.length, 1)
  assert.equal(run.lifecycle.filter(item => item === 'server-stop').length, 1)
})

test('macOS Quit proceeds when generation finishes during a window-only confirmation', async () => {
  const decision = deferred()
  const run = setup({ platform: 'darwin', confirm: () => decision.promise,
    readJobs: count => [{ status: count === 1 ? 'running' : 'complete' }] })
  run.window.close()
  await settle()
  run.app.quit()
  decision.resolve({ response: 1 })
  await settle()
  assert.equal(run.checks(), 2)
  assert.equal(run.dialogs.length, 1)
  assert.equal(run.window.isDestroyed(), true)
  assert.equal(run.lifecycle.filter(item => item === 'server-stop').length, 1)
})
