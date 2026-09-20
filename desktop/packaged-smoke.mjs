import { _electron } from 'playwright-core'
import assert from 'node:assert/strict'
import { access, mkdtemp, mkdir, readdir, readFile, symlink } from 'node:fs/promises'
import { execFileSync } from 'node:child_process'
import path from 'node:path'
import os from 'node:os'
import net from 'node:net'
import { fileURLToPath } from 'node:url'
import { setTimeout as delay } from 'node:timers/promises'

if (!process.env.CI || !['linux', 'darwin'].includes(process.platform)) throw new Error('Run on native CI runners')
const desktop = path.dirname(fileURLToPath(import.meta.url))
const root = path.resolve(process.argv[2])
const mac = process.platform === 'darwin'
const executablePath = mac ? path.join(root, 'ESPImageServer.app/Contents/MacOS/ESPImageServer') : path.join(root, 'espimageserver')
const resources = mac ? path.join(root, 'ESPImageServer.app/Contents/Resources') : path.join(root, 'resources')
const backend = path.join(resources, 'backend')
const expectedMode = process.argv[3] || 'management'
const manifest = JSON.parse(await readFile(path.join(backend, 'runtime-manifest.json'), 'utf8'))
assert.equal(manifest.mode, expectedMode)
assert.equal(manifest.target, `${process.platform}-${process.arch}`)
if (expectedMode === 'cuda') assert.equal(manifest.target, 'linux-x64')
const tool = path.join(resources, 'tools/esptool', mac ? 'esptool-macos-arm64' : 'esptool-linux-amd64', 'esptool')
assert.match(execFileSync(tool, ['version'], { encoding: 'utf8', timeout: 30000 }), /5\.1\.0/)
async function portFree() {
  const server = net.createServer()
  await new Promise((resolve, reject) => { server.once('error', reject); server.listen(8000, '127.0.0.1', () => server.close(resolve)) })
}
await portFree()
const storage = await mkdtemp(path.join(os.tmpdir(), 'esp-packaged-'))
await mkdir(path.join(storage, 'electron'))
// Linux serialport invokes udevadm. Expose only that OS utility, keeping system
// Python/FFmpeg unavailable instead of restoring the runner's entire PATH.
const toolsPath = path.join(storage, 'system-tools')
await mkdir(toolsPath)
if (!mac) {
  const udevadm = '/usr/bin/udevadm'
  await access(udevadm)
  await symlink(udevadm, path.join(toolsPath, 'udevadm'))
}
const env = { ...process.env, PATH: toolsPath, ESP_DESKTOP_SMOKE_STORAGE: storage,
  // Only the isolation/PID hook is supplied; app source must come from the bundle.
  PYTHONPATH: path.resolve(desktop, '../ci/smoke-python'), PYTHONDONTWRITEBYTECODE: '1',
  ESP_IMAGE_HOST: '127.0.0.1', ESP_IMAGE_PORT: '8000', ESP_IMAGE_OPEN_BROWSER: '0',
  HF_HUB_OFFLINE: '1', TRANSFORMERS_OFFLINE: '1', CUDA_VISIBLE_DEVICES: '' }
delete env.PYTHONHOME
delete env.ELECTRON_RUN_AS_NODE
for (const variable of ['LOCALAPPDATA', 'XDG_CONFIG_HOME', 'XDG_DATA_HOME', 'XDG_CACHE_HOME',
  'HF_HOME', 'HF_HUB_CACHE', 'HUGGINGFACE_HUB_CACHE', 'ESP_IMAGE_MODEL_CACHE']) env[variable] = path.join(storage, variable)
let application
try {
  application = await _electron.launch({ executablePath, cwd: storage, env, timeout: 60000,
    args: [`--user-data-dir=${path.join(storage, 'electron')}`, ...(mac ? [] : ['--no-sandbox'])] })
  const processInfo = await application.evaluate(({ app }) => ({ packaged: app.isPackaged, resources: process.resourcesPath }))
  assert.equal(processInfo.packaged, true)
  assert.equal(processInfo.resources, resources)
  let window = await application.firstWindow()
  async function check(page) {
    await page.waitForURL('http://127.0.0.1:8000/**', { timeout: 90000 })
    await page.locator('#app .v-application').waitFor()
    const state = await page.evaluate(() => window.espImageServerDesktop.getStartupState())
    assert.equal(state.status.title, 'Ready')
    const ports = await page.evaluate(() => window.espImageServerDesktop.firmwarePorts())
    assert.equal(ports.ok, true, JSON.stringify(ports))
  }
  await check(window)
  const health = await (await fetch('http://127.0.0.1:8000/health')).json()
  assert.equal(health.device, 'cpu')
  // Confirm the packaged interpreter imports app code from its own backend.
  const imported = execFileSync(path.join(backend, '.venv/bin/python'), ['-I', '-c',
    'import esp_image_server; print(esp_image_server.__file__)'], { env, encoding: 'utf8' }).trim()
  assert.ok(imported.startsWith(backend + path.sep), imported)
  if (expectedMode === 'cuda') {
    execFileSync(path.join(backend, '.venv/bin/python'), ['-I', '-c',
      "import torch, torchvision; from diffusers import AutoPipelineForText2Image, LTXPipeline, WanPipeline; assert torch.__version__ == '2.11.0+cu128'; assert torchvision.__version__ == '0.26.0+cu128'; assert torch.version.cuda == '12.8'; assert not torch.cuda.is_available()"],
    { env, timeout: 60000, stdio: 'inherit' })
    const rejected = await fetch('http://127.0.0.1:8000/models/Lykon/dreamshaper-8/select', { method: 'POST' })
    assert.equal(rejected.status, 400)
    assert.match((await rejected.json()).detail, /NVIDIA/)
  }
  if (mac) {
    await application.evaluate(async ({ BrowserWindow }) => {
      const current = BrowserWindow.getAllWindows()[0]
      await new Promise(resolve => { current.once('closed', resolve); current.close() })
    })
    assert.equal(await application.evaluate(({ BrowserWindow }) => BrowserWindow.getAllWindows().length), 0)
    ;[window] = await Promise.all([
      application.waitForEvent('window'),
      application.evaluate(({ app }) => app.emit('activate'))
    ])
    await check(window)
  }
  if (mac) await application.close()
  else {
    const closed = application.waitForEvent('close')
    await window.close()
    await closed
  }
  application = null
  const pids = (await readdir(storage)).filter(name => /^python-\d+\.pid$/.test(name)).map(name => Number(name.slice(7, -4)))
  assert.ok(pids.length)
  for (let attempt = 0; ; attempt++) {
    const alive = pids.some(pid => { try { process.kill(pid, 0); return true } catch { return false } })
    if (!alive) break
    assert.ok(attempt < 100, 'Packaged app left its Python server running')
    await delay(100)
  }
  await portFree()
  console.log(`PASS: packaged ${expectedMode} app, backend, frontend, preload, serial binding, esptool, and server shutdown`)
} finally {
  if (application) await application.close().catch(() => {})
  for (const name of await readdir(storage)) {
    if (/^python-\d+\.pid$/.test(name)) {
      try { process.kill(Number(name.slice(7, -4))) } catch { /* already exited */ }
    }
  }
}
