import assert from 'node:assert/strict'
import { spawn } from 'node:child_process'
import { mkdtemp, mkdir, readFile, readdir } from 'node:fs/promises'
import net from 'node:net'
import os from 'node:os'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { setTimeout as delay } from 'node:timers/promises'
import electron from 'electron'
import { runtimePaths, ServerRuntime } from './runtime.mjs'

const desktopDirectory = path.dirname(fileURLToPath(import.meta.url))
const runtime = runtimePaths({ desktopDirectory })
async function assertPortFree() {
  const probe = net.createServer()
  await new Promise((resolve, reject) => {
    probe.once('error', reject)
    probe.listen(8000, '127.0.0.1', () => probe.close(resolve))
  })
}
async function health() {
  try { return (await fetch('http://127.0.0.1:8000/health', { signal: AbortSignal.timeout(1000) })).ok }
  catch { return false }
}
async function waitFor(check, label) {
  const deadline = Date.now() + 60_000
  while (Date.now() < deadline) {
    if (await check()) return
    await delay(200)
  }
  throw new Error(`Timed out: ${label}`)
}
function alive(pid) {
  try { process.kill(pid, 0); return true } catch (error) { if (error.code === 'ESRCH') return false; throw error }
}
async function waitForPortFree() {
  await waitFor(async () => {
    try { await assertPortFree(); return true }
    catch (error) { if (error.code === 'EADDRINUSE') return false; throw error }
  }, 'port 8000 release')
}

// Never attach the test to the user's running server.
try { await assertPortFree() }
catch { throw new Error('Port 8000 is occupied. Close the app/server before running the desktop smoke test.') }
const root = await mkdtemp(path.join(os.tmpdir(), 'esp-desktop-smoke-'))
console.log(`Smoke diagnostics: ${root}`)
for (const scenario of ['owned', 'external']) {
  const storage = path.join(root, scenario)
  await mkdir(path.join(storage, 'electron'), { recursive: true })
  const env = { ...process.env, ESP_DESKTOP_SMOKE_STORAGE: storage,
    PYTHONPATH: [path.join(runtime.projectRoot, 'ci', 'smoke-python'), path.join(runtime.projectRoot, 'src')].join(path.delimiter),
    ESP_IMAGE_HOST: '127.0.0.1', ESP_IMAGE_PORT: '8000', ESP_IMAGE_OPEN_BROWSER: '0',
    HF_HUB_OFFLINE: '1', TRANSFORMERS_OFFLINE: '1' }
  delete env.ELECTRON_RUN_AS_NODE
  for (const variable of ['LOCALAPPDATA', 'XDG_CONFIG_HOME', 'XDG_DATA_HOME', 'XDG_CACHE_HOME',
    'ESP_IMAGE_MODEL_CACHE', 'HF_HOME', 'HF_HUB_CACHE', 'HUGGINGFACE_HUB_CACHE']) env[variable] = path.join(storage, variable)
  const external = new ServerRuntime(runtime, {
    spawnProcess: (command, args, options) => spawn(command, args, { ...options, env }),
    onOutput: data => process.stdout.write(data)
  })
  let child
  try {
    if (scenario === 'external') {
      external.start()
      await waitFor(health, 'external server startup')
    }
    console.log(`Testing ${scenario} server lifecycle`)
    // Hosted Linux runs in Xvfb without a configured Chromium sandbox.
    const flags = process.platform === 'linux' && process.env.CI ? ['--no-sandbox'] : []
    child = spawn(electron, [...flags, path.join(desktopDirectory, 'smoke-entry.mjs')], {
      cwd: runtime.projectRoot, env, stdio: 'inherit', windowsHide: true
    })
    const code = await new Promise((resolve, reject) => {
      const timer = setTimeout(() => { child.kill(); reject(new Error('Electron did not exit within 110 seconds')) }, 110_000)
      child.once('error', error => { clearTimeout(timer); reject(error) })
      child.once('exit', code => { clearTimeout(timer); resolve(code) })
    })
    assert.equal(code, 0, 'Electron must exit cleanly')
    const result = JSON.parse(await readFile(path.join(storage, 'result.json'), 'utf8'))
    assert.equal(result.loadedWindows, process.platform === 'darwin' ? 2 : 1)
    const pids = (await readdir(storage)).filter(name => /^python-\d+\.pid$/.test(name))
      .map(name => Number(name.slice(7, -4)))
    assert.ok(pids.length, 'Real Python server must start with isolated storage')
    if (scenario === 'external') {
      assert.ok(await health(), 'Desktop quit must preserve the external server')
      assert.ok(pids.every(alive), 'External Python process must remain alive')
    } else {
      await waitFor(() => pids.every(pid => !alive(pid)), 'owned Python process exit')
      await waitForPortFree()
    }
    console.log(`PASS: ${scenario} server lifecycle`)
  } finally {
    if (child && child.exitCode === null && child.signalCode === null) child.kill()
    await external.stop()
    // Failure cleanup is limited to interpreters recorded by this test's isolated startup hook.
    const cleanupPids = []
    for (const name of await readdir(storage)) {
      if (!/^python-\d+\.pid$/.test(name)) continue
      const pid = Number(name.slice(7, -4))
      cleanupPids.push(pid)
      try { if (alive(pid)) process.kill(pid) }
      catch (error) { if (error.code !== 'ESRCH') throw error }
    }
    await waitFor(() => cleanupPids.every(pid => !alive(pid)), 'test server cleanup')
  }
  await waitForPortFree()
}
