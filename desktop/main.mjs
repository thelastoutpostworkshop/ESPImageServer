import { app, BrowserWindow, dialog, ipcMain, screen, shell } from 'electron'
import { spawn } from 'node:child_process'
import { existsSync, readFileSync, writeFileSync } from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const desktopDirectory = path.dirname(fileURLToPath(import.meta.url))
const projectRoot = app.isPackaged
  ? path.resolve(process.resourcesPath, '..', '..')
  : path.resolve(desktopDirectory, '..')
const pythonPath = path.join(projectRoot, '.venv', 'Scripts', 'python.exe')
const appIcon = app.isPackaged
  ? path.join(projectRoot, 'espimageserver-icon.ico')
  : path.join(projectRoot, 'installer', 'assets', 'espimageserver-icon.ico')

let mainWindow
let serverProcess
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
    const response = await fetch('http://127.0.0.1:8000/health')
    return response.ok
  } catch {
    return false
  }
}

function startServer() {
  if (serverProcess || !existsSync(pythonPath)) return
  updateSplash('Starting local image service', 'Preparing the ESPImageServer Python environment…')
  serverProcess = spawn(pythonPath, ['-u', '-m', 'esp_image_server'], {
    cwd: projectRoot,
    env: { ...process.env, ESP_IMAGE_OPEN_BROWSER: '0' },
    windowsHide: true,
    stdio: ['ignore', 'pipe', 'pipe']
  })
  const trackServerOutput = data => {
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
  serverProcess.stdout.on('data', trackServerOutput)
  serverProcess.stderr.on('data', trackServerOutput)
  serverProcess.once('exit', () => { serverProcess = undefined })
}

async function waitForServer() {
  for (let attempt = 0; attempt < 180; attempt += 1) {
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
    icon: appIcon,
    webPreferences: {
      preload: path.join(desktopDirectory, 'preload.cjs'),
      contextIsolation: true,
      nodeIntegration: false
    }
  })
  if (savedPositionIsVisible(windowState)) mainWindow.setPosition(windowState.x, windowState.y)
  mainWindow.on('resize', scheduleWindowStateSave)
  mainWindow.on('move', scheduleWindowStateSave)
  mainWindow.on('maximize', scheduleWindowStateSave)
  mainWindow.on('unmaximize', scheduleWindowStateSave)
  mainWindow.on('close', saveWindowState)
  await mainWindow.loadFile(path.join(desktopDirectory, 'splash.html'), {
    query: { version: app.getVersion() }
  })
  sendToWindow('server-log', serverLogLines)
  mainWindow.show()
  if (windowState.isMaximized) mainWindow.maximize()

  if (!await serverIsAvailable()) startServer()
  else updateSplash('Connecting to ESPImageServer', 'The local image service is already running…')
  updateSplash('Waiting for ESPImageServer', 'The application is being prepared for local image & video generation…')
  if (await waitForServer()) {
    updateSplash('Ready', 'Opening the workspace…')
    await mainWindow.loadURL('http://127.0.0.1:8000/#generate')
  } else {
    await dialog.showMessageBox(mainWindow, {
      type: 'error',
      title: 'ESPImageServer could not start',
      message: 'The local image server did not become ready.',
      detail: 'Run the installer again to repair ESPImageServer, then try opening the app again.'
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

if (!app.requestSingleInstanceLock()) app.quit()
else {
  app.on('second-instance', () => {
    if (mainWindow) {
      if (mainWindow.isMinimized()) mainWindow.restore()
      mainWindow.focus()
    }
  })
  app.whenReady().then(createWindow)
  app.on('window-all-closed', () => app.quit())
  app.on('before-quit', () => {
    isQuitting = true
    clearTimeout(saveWindowStateTimer)
    if (serverProcess) serverProcess.kill()
  })
}
