import path from 'node:path'
import { existsSync } from 'node:fs'
import { spawn } from 'node:child_process'

export function runtimePaths({ desktopDirectory, resourcesPath, packaged = false,
  platform = process.platform, arch = process.arch }) {
  const paths = platform === 'win32' ? path.win32 : path.posix
  const projectRoot = packaged
    ? (platform === 'win32' ? paths.resolve(resourcesPath, '..', '..') : paths.join(resourcesPath, 'backend'))
    : paths.resolve(desktopDirectory, '..')
  // Non-Windows bundle layout is a contract for future packaging, not a bundled runtime yet.
  const pythonPath = paths.join(projectRoot, '.venv', ...(platform === 'win32' ? ['Scripts', 'python.exe'] : ['bin', 'python']))
  const toolTargets = { 'win32-x64': 'windows-amd64', 'linux-x64': 'linux-amd64',
    'linux-arm64': 'linux-aarch64', 'darwin-x64': 'macos-amd64', 'darwin-arm64': 'macos-arm64' }
  const target = toolTargets[`${platform}-${arch}`]
  return {
    projectRoot, pythonPath, platform, arch, packaged,
    toolPath: target ? paths.join(packaged ? resourcesPath : desktopDirectory, 'tools', 'esptool',
      `esptool-${target}`, platform === 'win32' ? 'esptool.exe' : 'esptool') : null,
    appIcon: platform === 'win32' ? (packaged ? paths.join(projectRoot, 'espimageserver-icon.ico')
      : paths.join(projectRoot, 'installer', 'assets', 'espimageserver-icon.ico')) : undefined
  }
}

export function requireRuntimeFile(file, label, runtime, exists = existsSync) {
  const help = runtime.packaged ? 'Repair the application installation.' : 'Prepare the local development dependencies.'
  if (!file) throw new Error(`${label} is not configured for ${runtime.platform}/${runtime.arch}. ${help}`)
  if (!exists(file)) throw new Error(`${label} was not found at ${file}. ${help}`)
  return file
}

export function registerWindowLifecycle(app, { platform = process.platform, getWindow, createWindow,
  isQuitting, onError }) {
  let opening = false
  const showWindow = () => {
    if (isQuitting()) return
    const window = getWindow()
    if (window && !window.isDestroyed()) {
      if (window.isMinimized()) window.restore()
      window.focus()
    } else if (app.isReady() && !opening) {
      opening = true
      void Promise.resolve().then(() => { if (!isQuitting()) return createWindow() })
        .catch(onError).finally(() => { opening = false })
    }
  }
  app.on('second-instance', showWindow)
  app.on('activate', showWindow)
  app.whenReady().then(showWindow).catch(onError)
  app.on('window-all-closed', () => { if (platform !== 'darwin') app.quit() })
}

// Own only the Python process we launch. Connecting to an existing server never
// gives this desktop instance authority to stop it.
export class ServerRuntime {
  constructor(runtime, { spawnProcess = spawn, exists = existsSync, onOutput = () => {} } = {}) {
    this.runtime = runtime
    this.spawnProcess = spawnProcess
    this.exists = exists
    this.onOutput = onOutput
    this.child = null
    this.error = null
    this.stopping = false
  }

  start() {
    if (this.child) return
    this.error = null
    this.stopping = false
    const executable = requireRuntimeFile(this.runtime.pythonPath, 'Python runtime', this.runtime, this.exists)
    const child = this.spawnProcess(executable, ['-u', '-m', 'esp_image_server'], {
      cwd: this.runtime.projectRoot, env: { ...process.env, ESP_IMAGE_OPEN_BROWSER: '0' },
      windowsHide: true, shell: false, stdio: ['ignore', 'pipe', 'pipe']
    })
    this.child = child
    child.stdout.on('data', this.onOutput)
    child.stderr.on('data', this.onOutput)
    child.once('error', error => {
      this.error = new Error(`Could not start Python at ${executable}: ${error.message}`)
      if (this.child === child) this.child = null
    })
    child.once('exit', (code, signal) => {
      if (!this.stopping && !this.error) this.error = new Error(`The local Python server stopped (${signal || code}). Check the startup log.`)
      if (this.child === child) this.child = null
    })
  }

  async stop(timeout = 5000) {
    const child = this.child
    if (!child) return
    this.stopping = true
    await new Promise(resolve => {
      let timer
      const finish = () => { clearTimeout(timer); child.removeListener('exit', finish); child.removeListener('error', finish); resolve() }
      child.once('exit', finish)
      child.once('error', finish)
      timer = setTimeout(() => {
        try { child.kill('SIGKILL') } catch { /* Process may already have exited. */ }
        finish()
      }, timeout)
      try {
        if (this.runtime.platform === 'win32' && child.pid) {
          // The venv launcher can own the real Python process on Windows.
          const killer = this.spawnProcess('taskkill.exe', ['/PID', String(child.pid), '/T', '/F'],
            { windowsHide: true, shell: false, stdio: 'ignore' })
          killer.once('error', () => { try { child.kill() } catch { finish() } })
          killer.once('exit', code => { if (code !== 0) { try { child.kill() } catch { finish() } } })
        } else child.kill()
      } catch { finish() }
    })
    if (this.child === child) this.child = null
  }
}
