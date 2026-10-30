import test from 'node:test'
import assert from 'node:assert/strict'
import { EventEmitter } from 'node:events'
import { execFileSync } from 'node:child_process'
import { existsSync } from 'node:fs'
import { mkdir, mkdtemp, rm, writeFile } from 'node:fs/promises'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { runtimePaths, requireRuntimeFile, ServerRuntime, registerWindowLifecycle } from './runtime.mjs'
import { smokePythonArguments } from './smoke-python.mjs'

test('Windows installation uses private Python while development keeps its virtual environment', () => {
  const dev = runtimePaths({ desktopDirectory: 'C:\\My Repo\\desktop', platform: 'win32', arch: 'x64' })
  assert.equal(dev.pythonPath, 'C:\\My Repo\\.venv\\Scripts\\python.exe')
  assert.equal(dev.toolPath, 'C:\\My Repo\\desktop\\tools\\esptool\\esptool-windows-amd64\\esptool.exe')
  const installed = runtimePaths({ packaged: true, resourcesPath: 'C:\\Apps\\ESP\\desktop\\resources', platform: 'win32', arch: 'x64' })
  assert.equal(installed.projectRoot, 'C:\\Apps\\ESP')
  assert.equal(installed.pythonPath, 'C:\\Apps\\ESP\\runtime\\python.exe')
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

for (const packaged of [false, true]) {
  test(`Windows ${packaged ? 'packaged' : 'development'} startup isolates Python without changing app configuration`, () => {
    const environment = Object.freeze({
      PYTHONHOME: 'C:\\Old Python', pythonpath: 'C:\\Another app', PythonHome: 'C:\\Third Python',
      ESP_IMAGE_MODEL_CACHE: 'C:\\My models', ESP_IMAGE_PORT: '8123', PATH: 'C:\\System tools',
      PYTHONUTF8: '1', ESP_IMAGE_OPEN_BROWSER: '1'
    })
    const { server, calls } = fixture({ environment })
    server.runtime = runtimePaths({ packaged, platform: 'win32', arch: 'x64',
      desktopDirectory: 'C:\\My Repo\\desktop', resourcesPath: 'C:\\Apps\\ESP\\desktop\\resources' })
    server.start()
    assert.equal(calls[0][0], packaged ? 'C:\\Apps\\ESP\\runtime\\python.exe' : 'C:\\My Repo\\.venv\\Scripts\\python.exe')
    assert.deepEqual(calls[0][1], [packaged ? '-I' : '-E', '-u', '-m', 'esp_image_server'])
    assert.deepEqual(calls[0][2].env, {
      ESP_IMAGE_MODEL_CACHE: environment.ESP_IMAGE_MODEL_CACHE, ESP_IMAGE_PORT: '8123',
      PATH: environment.PATH, PYTHONUTF8: '1', ESP_IMAGE_OPEN_BROWSER: '0'
    })
    assert.equal(environment.PYTHONHOME, 'C:\\Old Python')
    assert.equal(environment.pythonpath, 'C:\\Another app')
    assert.equal(calls[0][2].windowsHide, true)
    assert.equal(calls[0][2].shell, false)
  })
}

test('smoke instrumentation wraps only the Windows server module entry', () => {
  const args = ['-E', '-u', '-m', 'esp_image_server']
  const wrapped = smokePythonArguments(args, 'win32')
  assert.deepEqual(wrapped.slice(0, 2), ['-E', '-u'])
  assert.ok(wrapped[2].endsWith(path.join('ci', 'smoke-python', 'run-server.py')))
  assert.deepEqual(smokePythonArguments(args, 'linux'), args)
  assert.deepEqual(smokePythonArguments(args, 'darwin'), args)
  const killArgs = ['/PID', '1234', '/T', '/F']
  assert.deepEqual(smokePythonArguments(killArgs, 'win32'), killArgs)
})

const workspace = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
const testPython = path.join(workspace, '.venv', 'Scripts', 'python.exe')
test('real Windows Python startup ignores conflicting account variables', {
  skip: process.platform !== 'win32' || !existsSync(testPython)
}, async t => {
  const temporary = await mkdtemp(path.join(workspace, '.tmp-runtime-startup-'))
  const root = path.join(temporary, 'User é 日本語')
  const prefix = path.join(root, 'fixture-python')
  await mkdir(root)
  try {
    // Only a no-pip test venv and a print-only module are created. No app code,
    // server ports, package downloads, user settings, or GPUs are touched.
    execFileSync(testPython, ['-I', '-m', 'venv', '--without-pip', prefix], { timeout: 30000, windowsHide: true })
    await writeFile(path.join(prefix, 'Lib', 'site-packages', 'esp_image_server.py'), `
import json, os, sys
print(json.dumps({"isolated": sys.flags.isolated, "ignore_environment": sys.flags.ignore_environment,
                  "home": os.environ.get("PYTHONHOME"), "path": os.environ.get("PYTHONPATH"),
                  "cache": os.environ.get("ESP_IMAGE_MODEL_CACHE")}))
`)
    for (const packaged of [false, true]) {
      await t.test(packaged ? 'packaged isolation flags' : 'development isolation flags', async () => {
        let output = ''
        const runtime = { packaged, platform: 'win32', projectRoot: root,
          pythonPath: path.join(prefix, 'Scripts', 'python.exe') }
        const environment = { ...process.env, PATH: '', PYTHONHOME: path.join(root, 'missing-home'),
          PYTHONPATH: path.join(root, 'missing-packages'), ESP_IMAGE_MODEL_CACHE: path.join(root, 'models') }
        const server = new ServerRuntime(runtime, { environment, onOutput: data => { output += data.toString() } })
        try {
          server.start()
          await new Promise((resolve, reject) => {
            const timer = setTimeout(() => reject(new Error('Fixture interpreter did not exit')), 15000)
            server.child.once('error', error => { clearTimeout(timer); reject(error) })
            server.child.once('close', code => {
              clearTimeout(timer)
              if (code === 0) resolve()
              else reject(new Error(`Fixture interpreter failed (${code}): ${output}`))
            })
          })
          assert.deepEqual(JSON.parse(output), { isolated: Number(packaged), ignore_environment: 1,
            home: null, path: null, cache: environment.ESP_IMAGE_MODEL_CACHE })
          assert.ok(environment.PYTHONHOME.endsWith('missing-home'))
          assert.ok(environment.PYTHONPATH.endsWith('missing-packages'))
        } finally {
          await server.stop()
        }
      })
    }
  } finally {
    assert.equal(path.dirname(temporary), workspace)
    assert.ok(path.basename(temporary).startsWith('.tmp-runtime-startup-'))
    await rm(temporary, { recursive: true, force: true })
  }
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
