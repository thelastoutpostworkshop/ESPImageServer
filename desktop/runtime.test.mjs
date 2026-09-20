import test from 'node:test'
import assert from 'node:assert/strict'
import { EventEmitter } from 'node:events'
import { runtimePaths, requireRuntimeFile, ServerRuntime, registerWindowLifecycle } from './runtime.mjs'

test('Windows development and installed paths remain unchanged', () => {
  const dev = runtimePaths({ desktopDirectory: 'C:\\My Repo\\desktop', platform: 'win32', arch: 'x64' })
  assert.equal(dev.pythonPath, 'C:\\My Repo\\.venv\\Scripts\\python.exe')
  assert.equal(dev.toolPath, 'C:\\My Repo\\desktop\\tools\\esptool\\esptool-windows-amd64\\esptool.exe')
  const installed = runtimePaths({ packaged: true, resourcesPath: 'C:\\Apps\\ESP\\desktop\\resources', platform: 'win32', arch: 'x64' })
  assert.equal(installed.projectRoot, 'C:\\Apps\\ESP')
  assert.equal(installed.pythonPath, 'C:\\Apps\\ESP\\.venv\\Scripts\\python.exe')
  assert.equal(installed.appIcon, 'C:\\Apps\\ESP\\espimageserver-icon.ico')
})

for (const platform of ['linux', 'darwin']) {
  for (const arch of ['x64', 'arm64']) {
    test(`${platform}/${arch} resolves POSIX paths independently of host OS`, () => {
      const dev = runtimePaths({ desktopDirectory: '/home/User space/desktop', platform, arch })
      assert.equal(dev.pythonPath, '/home/User space/.venv/bin/python')
      assert.ok(dev.toolPath.endsWith('/esptool'))
      assert.equal(dev.appIcon, undefined)
      const installed = runtimePaths({ packaged: true, resourcesPath: '/My App/Resources', platform, arch })
      assert.equal(installed.pythonPath, '/My App/Resources/backend/.venv/bin/python')
      assert.ok(installed.toolPath.startsWith('/My App/Resources/tools/'))
    })
  }
}

test('missing tools and unsupported architectures produce actionable errors', () => {
  const runtime = runtimePaths({ desktopDirectory: '/repo/desktop', platform: 'linux', arch: 'riscv64' })
  assert.throws(() => requireRuntimeFile(runtime.toolPath, 'esptool', runtime), /not configured for linux\/riscv64/)
  assert.throws(() => requireRuntimeFile(runtime.pythonPath, 'Python', runtime, () => false), /Prepare the local development dependencies/)
  assert.throws(() => requireRuntimeFile('/missing', 'Python', { ...runtime, packaged: true }, () => false), /Repair the application/)
})

function fixture(overrides = {}) {
  const child = new EventEmitter()
  child.pid = 1234
  child.stdout = new EventEmitter()
  child.stderr = new EventEmitter()
  const signals = []
  child.kill = signal => { signals.push(signal); child.emit('exit', 0, signal) }
  const calls = [], output = []
  const runtime = runtimePaths({ desktopDirectory: '/repo/desktop', platform: 'linux', arch: 'x64' })
  const server = new ServerRuntime(runtime, {
    exists: () => true,
    spawnProcess: (...args) => { calls.push(args); return child },
    onOutput: data => output.push(data), ...overrides
  })
  return { server, child, calls, signals, output }
}

test('missing Python fails immediately without spawning', () => {
  const { server, calls } = fixture({ exists: () => false })
  assert.throws(() => server.start(), /Python runtime was not found/)
  assert.equal(calls.length, 0)
})

test('launch is single-instance, forwards logs and stops only an owned server', async () => {
  const { server, child, calls, signals, output } = fixture()
  await server.stop()
  assert.deepEqual(signals, [])
  server.start()
  server.start()
  assert.equal(calls.length, 1)
  assert.deepEqual(calls[0][1], ['-u', '-m', 'esp_image_server'])
  assert.equal(calls[0][2].shell, false)
  assert.equal(calls[0][2].env.ESP_IMAGE_OPEN_BROWSER, '0')
  child.stdout.emit('data', 'hello')
  child.stderr.emit('data', 'diagnostic')
  assert.deepEqual(output, ['hello', 'diagnostic'])
  await server.stop()
  assert.equal(server.child, null)
  assert.equal(server.error, null)
  assert.equal(signals.length, 1)
})

test('spawn errors and early exits are recorded instead of becoming uncaught errors', () => {
  const { server, child } = fixture()
  server.start()
  child.emit('error', new Error('EACCES'))
  assert.match(server.error.message, /Could not start Python.*EACCES/)
  assert.equal(server.child, null)
  server.start()
  child.emit('exit', 7)
  assert.match(server.error.message, /server stopped \(7\)/)
})

test('shutdown is bounded and escalates if termination is ignored', async () => {
  const { server, child, signals } = fixture()
  child.kill = signal => { signals.push(signal) }
  server.start()
  await server.stop(5)
  assert.deepEqual(signals, [undefined, 'SIGKILL'])
})

test('Windows shutdown targets the owned Python process tree', async () => {
  const { server, child } = fixture()
  server.runtime.platform = 'win32'
  server.start()
  const calls = []
  server.spawnProcess = (...args) => {
    calls.push(args)
    queueMicrotask(() => child.emit('exit', 0))
    return new EventEmitter()
  }
  await server.stop()
  assert.equal(calls[0][0], 'taskkill.exe')
  assert.deepEqual(calls[0][1], ['/PID', '1234', '/T', '/F'])
  assert.equal(calls[0][2].windowsHide, true)
})

for (const platform of ['win32', 'linux', 'darwin']) {
  test(`${platform} window lifecycle reopens, focuses, and respects quit`, async () => {
    const app = new EventEmitter()
    let quits = 0, creates = 0, focuses = 0, restores = 0, window, quitting = false
    app.isReady = () => true
    app.whenReady = () => Promise.resolve()
    app.quit = () => quits++
    const createWindow = () => {
      creates++
      window = { isDestroyed: () => false, isMinimized: () => true,
        restore: () => restores++, focus: () => focuses++ }
    }
    registerWindowLifecycle(app, { platform, getWindow: () => window, createWindow,
      isQuitting: () => quitting, onError: assert.fail })
    await new Promise(resolve => setImmediate(resolve))
    assert.equal(creates, 1)
    app.emit('second-instance')
    assert.equal(focuses, 1)
    assert.equal(restores, 1)
    window = undefined
    app.emit('window-all-closed')
    assert.equal(quits, platform === 'darwin' ? 0 : 1)
    app.emit('activate')
    await new Promise(resolve => setImmediate(resolve))
    assert.equal(creates, 2)
    quitting = true
    window = undefined
    app.emit('activate')
    await new Promise(resolve => setImmediate(resolve))
    assert.equal(creates, 2)
  })
}
