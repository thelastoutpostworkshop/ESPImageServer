import { app, BrowserWindow, dialog, ipcMain, screen, shell } from 'electron'
import { readFileSync, writeFileSync } from 'node:fs'
import path from 'node:path'
import { fileURLToPath, pathToFileURL } from 'node:url'
import { runtimePaths, requireRuntimeFile, ServerRuntime, registerWindowLifecycle } from './runtime.mjs'
import { FirmwareInstaller, runProcess } from './firmware.mjs'
import { identifyPort, identifyAfterFlash, serialPorts } from './identification.mjs'
import { WifiSetup } from './wifi.mjs'
import { FirmwareLibrary } from './firmware-library.mjs'
import { FirmwareReleases } from './firmware-releases.mjs'
import { GenerationSetup } from './generation-setup.mjs'

const desktopDirectory = path.dirname(fileURLToPath(import.meta.url))
const runtime = runtimePaths({ desktopDirectory, resourcesPath: process.resourcesPath, packaged: app.isPackaged })
const firmwareInstaller = new FirmwareInstaller(runtime.toolPath,
  { ports: serialPorts, identify: identifyPort, reconnect: identifyAfterFlash,
    run: (tool, args, options) => runProcess(requireRuntimeFile(tool, 'USB flashing tool (esptool)', runtime), args, options) })
const wifiSetup = new WifiSetup(firmwareInstaller)
const firmwareLibrary = new FirmwareLibrary(path.join(app.getPath('userData'), 'firmware-library.json'))
const firmwareReleases = new FirmwareReleases(path.join(app.getPath('userData'), 'firmware-downloads'))
let mainWindow
let saveWindowStateTimer
let isQuitting = false
const serverLogLines = []

const defaultWindowState = { width: 1440, height: 940, isMaximized: false }

function getWindowStatePath() {
  return path.join(app.getPath('userData'), 'window-state.json')
}

function loadWindowState() {
  try {
    const saved = JSON.parse(readFileSync(getWindowStatePath(), 'utf8'))
    if (!Number.isFinite(saved.width) || !Number.isFinite(saved.height)) return defaultWindowState
    return { ...defaultWindowState, ...saved }
  } catch {
    return defaultWindowState
  }
}

function savedPositionIsVisible({ x, y, width, height }) {
  if (!Number.isFinite(x) || !Number.isFinite(y)) return false
  return screen.getAllDisplays().some(({ workArea }) =>
    x + width > workArea.x && x < workArea.x + workArea.width &&
    y + height > workArea.y && y < workArea.y + workArea.height)
}

function saveWindowState() {
  if (!mainWindow || mainWindow.isDestroyed()) return
  const bounds = mainWindow.getNormalBounds()
  try {
    writeFileSync(getWindowStatePath(), JSON.stringify({
      ...bounds,
      isMaximized: mainWindow.isMaximized()
    }), 'utf8')
  } catch {
    // Failing to save window state should never prevent the application closing.
  }
}

function scheduleWindowStateSave() {
  clearTimeout(saveWindowStateTimer)
  saveWindowStateTimer = setTimeout(saveWindowState, 300)
}
let splashStatus = { title: 'Starting ESPImageServer', detail: 'Loading the local image-generation service…' }

function sendToWindow(channel, payload) {
  if (isQuitting || !mainWindow || mainWindow.isDestroyed() || mainWindow.webContents.isDestroyed()) return
  mainWindow.webContents.send(channel, payload)
}

function updateSplash(title, detail) {
  splashStatus = { title, detail }
  sendToWindow('server-status', splashStatus)
}

function appendServerLog(data) {
  const lines = data.toString().replaceAll('\r', '\n').split('\n').filter(Boolean)
  if (!lines.length) return
  serverLogLines.push(...lines)
  if (serverLogLines.length > 120) serverLogLines.splice(0, serverLogLines.length - 120)
  sendToWindow('server-log', lines)
}

async function serverIsAvailable() {
  try {
    const response = await fetch('http://127.0.0.1:8000/health', { signal: AbortSignal.timeout(2000) })
    return response.ok
  } catch {
    return false
  }
}

const serverRuntime = new ServerRuntime(runtime, {
  onOutput: data => {
    appendServerLog(data)
    const line = data.toString()
    if (line.includes('Loading weights')) {
      updateSplash('Loading AI model weights', 'This can take a few minutes, especially on the first desktop start.')
    } else if (line.includes('Loading pipeline components')) {
      updateSplash('Preparing image-generation components', 'Almost ready…')
    } else if (line.includes('Image model is ready')) {
      updateSplash('AI model ready', 'Starting the ESPImageServer workspace…')
    }
  }
})
const generationSetup = new GenerationSetup({ onStatus: updateSplash, onLog: appendServerLog })

let setupChoice
function chooseSetup(title, detail, actions) {
  splashStatus = { title, detail, actions }
  sendToWindow('server-status', splashStatus)
  return new Promise(resolve => { setupChoice = resolve })
}
ipcMain.handle('generation-setup-action', (event, action) => {
  if (event.sender !== mainWindow?.webContents || event.senderFrame !== mainWindow.webContents.mainFrame ||
      event.senderFrame.url.split('?')[0] !== pathToFileURL(path.join(desktopDirectory, 'splash.html')).href ||
      !splashStatus.actions?.some(item => item.id === action) || !setupChoice) throw new Error('Setup action is unavailable')
  const resolve = setupChoice; setupChoice = null
  updateSplash('Preparing generation setup', 'Please wait...')
  resolve(action)
})
async function prepareGeneration(window) {
  if (!app.isPackaged || process.platform !== 'linux') return
  for (;;) {
    let action
    try {
      const result = await generationSetup.start(runtime, path.join(app.getPath('userData'), 'generation-runtime'))
      if (isQuitting || window.isDestroyed()) return
      if (result.kind === 'ready') { runtime.pythonPath = result.python; return }
      action = await chooseSetup('Generation is unavailable', result.detail,
        [{ id: 'retry', label: 'Retry GPU check' }, { id: 'tools', label: 'Open display tools' }, { id: 'quit', label: 'Quit' }])
    } catch (error) {
      if (isQuitting || window.isDestroyed()) return
      action = await chooseSetup('Generation setup could not finish', error.message,
        [{ id: 'retry', label: 'Retry setup' }, { id: 'quit', label: 'Quit' }])
    }
    if (action === 'tools') return
    if (action === 'quit' || isQuitting || window.isDestroyed()) { app.quit(); return }
  }
}

async function waitForServer(window) {
  const deadline = performance.now() + 180_000
  while (performance.now() < deadline) {
    if (isQuitting || window.isDestroyed()) return false
    if (serverRuntime.error) throw serverRuntime.error
    if (await serverIsAvailable()) return true
    await new Promise(resolve => setTimeout(resolve, 1_000))
  }
  return false
}

async function createWindow() {
  const windowState = loadWindowState()
  mainWindow = new BrowserWindow({
    width: Math.max(960, windowState.width),
    height: Math.max(700, windowState.height),
    minWidth: 960,
    minHeight: 700,
    autoHideMenuBar: true,
    show: false,
    icon: runtime.appIcon,
    webPreferences: {
      preload: path.join(desktopDirectory, 'preload.cjs'),
      contextIsolation: true,
      nodeIntegration: false
    }
  })
  const window = mainWindow
  // Store and other HTTPS links belong in the user's browser, not a new app window.
  window.webContents.setWindowOpenHandler(({ url }) => {
    try {
      const destination = new URL(url)
      if (destination.protocol === 'https:' && !destination.username && !destination.password) {
        shell.openExternal(destination.href).catch(error => console.warn('Could not open browser link:', error.message))
      }
    } catch { /* Invalid URLs must not open a desktop window. */ }
    return { action: 'deny' }
  })
  window.on('closed', () => { if (mainWindow === window) mainWindow = undefined })
  if (savedPositionIsVisible(windowState)) mainWindow.setPosition(windowState.x, windowState.y)
  mainWindow.on('resize', scheduleWindowStateSave)
  mainWindow.on('move', scheduleWindowStateSave)
  mainWindow.on('maximize', scheduleWindowStateSave)
  mainWindow.on('unmaximize', scheduleWindowStateSave)
  mainWindow.on('close', event => {
    if (firmwareInstaller.state.busy) {
      event.preventDefault()
      dialog.showMessageBoxSync(mainWindow, { type: 'info', message: 'Firmware installation is in progress.', detail: 'Wait for the result before closing ESPImageServer.' })
      return
    }
    saveWindowState()
  })
  await window.loadFile(path.join(desktopDirectory, 'splash.html'), {
    query: { version: app.getVersion() }
  })
  sendToWindow('server-log', serverLogLines)
  if (isQuitting || window.isDestroyed()) return
  window.show()
  if (windowState.isMaximized) window.maximize()

  try {
    const available = await serverIsAvailable()
    if (isQuitting || window.isDestroyed()) return
    if (!available) {
      await prepareGeneration(window)
      if (isQuitting || window.isDestroyed()) return
      serverRuntime.start()
    }
    updateSplash('Waiting for ESPImageServer', 'Preparing the local image and video service...')
    if (await waitForServer(window)) {
      if (isQuitting || window.isDestroyed()) return
      updateSplash('Ready', 'Opening the workspace...')
      await window.loadURL('http://127.0.0.1:8000/#generate')
    } else if (!isQuitting && !window.isDestroyed()) {
      throw new Error('The local image server did not become ready within three minutes. Check the startup log.')
    }
  } catch (error) {
    if (isQuitting || window.isDestroyed()) return
    updateSplash('ESPImageServer could not start', error.message)
    await dialog.showMessageBox(window, {
      type: 'error', title: 'ESPImageServer could not start',
      message: 'The local image server could not start.', detail: error.message
    })
  }
}

ipcMain.handle('choose-image-library', async () => {
  const result = await dialog.showOpenDialog(mainWindow, {
    title: 'Choose an empty folder for ESPImageServer images',
    properties: ['openDirectory', 'createDirectory']
  })
  return result.canceled ? null : result.filePaths[0]
})

ipcMain.handle('reveal-image-library', async (_, libraryPath) => shell.openPath(libraryPath))
ipcMain.handle('startup-state', () => ({ status: splashStatus, lines: serverLogLines }))

function requireFirmwareSender(event) {
  if (event.sender !== mainWindow?.webContents || event.senderFrame !== mainWindow.webContents.mainFrame ||
      new URL(event.senderFrame.url).origin !== 'http://127.0.0.1:8000') {
    throw new Error('Firmware installation is available only in the local desktop window.')
  }
}
for (const [channel, handler] of Object.entries({
  'firmware-state': () => firmwareInstaller.snapshot(),
  'firmware-releases': () => firmwareReleases.check(),
  'firmware-releases-check': () => firmwareReleases.check(true),
  'firmware-download-state': () => firmwareReleases.snapshot(),
  'firmware-download-cancel': () => firmwareReleases.cancel(),
  'firmware-release-select': request => firmwareReleases.select(request, firmwareInstaller),
  'firmware-library': () => firmwareLibrary.load(),
  'firmware-library-check': () => firmwareLibrary.scan(),
  'firmware-library-choose': async () => {
    if (firmwareInstaller.state.busy) throw new Error('Wait for USB work to finish.')
    const result = await dialog.showOpenDialog(mainWindow, {
      title: 'Choose your firmware library (contains board and version folders)', properties: ['openDirectory']
    })
    return result.canceled ? firmwareLibrary.snapshot() : firmwareLibrary.choose(result.filePaths[0])
  },
  'firmware-library-select': ({ directory } = {}) => firmwareLibrary.select(directory, firmwareInstaller),
  'firmware-ports': () => firmwareInstaller.refreshPorts(),
  'firmware-select-port': ({ port } = {}) => firmwareInstaller.selectPort(port),
  'firmware-identify': ({ port } = {}) => firmwareInstaller.identifyFirmware(port),
  'firmware-refresh-identity': ({ port } = {}) => firmwareInstaller.refreshIdentity(port),
  'firmware-wifi-start': request => wifiSetup.start(request),
  'firmware-wifi-cancel': () => wifiSetup.cancel(),
  'firmware-package': async () => {
    if (firmwareInstaller.state.busy) throw new Error('Wait for the current firmware operation.')
    const result = await dialog.showOpenDialog(mainWindow, {
      title: 'Choose the firmware version folder containing manifest.json', properties: ['openDirectory']
    })
    if (!result.canceled) await firmwareInstaller.select(result.filePaths[0])
    return firmwareInstaller.snapshot()
  },
  'firmware-install': ({ port, board, baud } = {}) => {
    requireRuntimeFile(runtime.toolPath, 'USB flashing tool (esptool)', runtime)
    return firmwareInstaller.start(port, board, baud)
  }
})) {
  ipcMain.handle(channel, async (event, payload) => {
    requireFirmwareSender(event)
    if (firmwareReleases.state.busy && !['firmware-state', 'firmware-download-state', 'firmware-download-cancel'].includes(channel)) {
      return { ok: false, error: 'Wait for the firmware download to finish or cancel it.' }
    }
    try { return { ok: true, value: await handler(payload) } }
    catch (error) { return { ok: false, error: error.message } }
  })
}

if (!app.requestSingleInstanceLock()) app.quit()
else {
  registerWindowLifecycle(app, {
    getWindow: () => mainWindow, createWindow, isQuitting: () => isQuitting,
    onError: error => { if (!isQuitting) dialog.showErrorBox('ESPImageServer could not open', error.message) }
  })
  let shutdownComplete = false
  app.on('before-quit', event => {
    if (shutdownComplete) return
    if (isQuitting) { event.preventDefault(); return }
    if (wifiSetup.running) {
      event.preventDefault(); wifiSetup.cancel()
      void wifiSetup.completion.finally(() => app.quit())
      return
    }
    if (firmwareInstaller.state.busy) { event.preventDefault(); return }
    isQuitting = true
    setupChoice?.('quit'); setupChoice = null
    clearTimeout(saveWindowStateTimer)
    event.preventDefault()
    void generationSetup.stop().then(() => serverRuntime.stop()).finally(() => { shutdownComplete = true; app.quit() })
  })
}
