// Test-only entry point: exercise the real main module without production hooks.
import { app, BrowserWindow, dialog, shell } from 'electron'
import assert from 'node:assert/strict'
import { writeFileSync } from 'node:fs'
import path from 'node:path'
import { setTimeout as delay } from 'node:timers/promises'
import { ServerRuntime } from './runtime.mjs'
import { smokePythonArguments } from './smoke-python.mjs'

const storage = process.env.ESP_DESKTOP_SMOKE_STORAGE
if (!storage) throw new Error('Launch through npm run test:smoke.')
// Keep test instrumentation outside the production runtime. Only the server
// module entry is wrapped; native tools and process-tree cleanup stay unchanged.
if (process.platform === 'win32') {
  const start = ServerRuntime.prototype.start
  ServerRuntime.prototype.start = function () {
    const spawn = this.spawnProcess
    this.spawnProcess = (command, args, options) => spawn(command, smokePythonArguments(args), options)
    try { return start.call(this) } finally { this.spawnProcess = spawn }
  }
}
app.setPath('userData', path.join(storage, 'electron'))
let completed = false
let loadedWindows = 0
function fail(error) {
  console.error(error)
  app.exit(1)
}
// A startup error must fail CI instead of waiting behind a modal dialog.
dialog.showMessageBox = async (_window, options) => { throw new Error(JSON.stringify(options)) }
dialog.showErrorBox = (title, content) => fail(new Error(`${title}: ${content}`))
process.on('unhandledRejection', fail)
const watchdog = setTimeout(() => fail(new Error('Desktop smoke test timed out')), 90_000)
app.on('will-quit', () => {
  clearTimeout(watchdog)
  if (!completed) process.exitCode = 1
})
app.on('browser-window-created', (_event, window) => {
  window.webContents.on('render-process-gone', (_event, details) => fail(new Error(JSON.stringify(details))))
  window.webContents.on('did-finish-load', () => {
    if (!window.webContents.getURL().startsWith('http://127.0.0.1:8000/')) return
    void checkWindow(window).catch(fail)
  })
})
async function checkWindow(window) {
  const deadline = Date.now() + 20_000
  let mounted = false
  while (Date.now() < deadline) {
    mounted = await window.webContents.executeJavaScript(`Boolean(
      document.querySelector('#app .v-application') &&
      document.querySelector('#app')?.innerText.includes('Generate image'))`)
    if (mounted) break
    await delay(100)
  }
  assert.ok(mounted, 'Vue workspace must render, not just the splash or an empty page')
  const startup = await window.webContents.executeJavaScript('window.espImageServerDesktop.getStartupState()')
  assert.equal(startup.status.title, 'Ready', 'preload IPC must reach the real main process')
  await checkFolderActions(window)
  loadedWindows += 1
  console.log(`Workspace loaded (${loadedWindows}); preload IPC passed`)
  if (process.platform === 'darwin' && loadedWindows === 1) {
    window.close()
    await delay(250)
    assert.equal(BrowserWindow.getAllWindows().length, 0)
    assert.ok((await fetch('http://127.0.0.1:8000/health')).ok)
    app.emit('activate')
    return
  }
  completed = true
  writeFileSync(path.join(storage, 'result.json'), JSON.stringify({ loadedWindows, platform: process.platform }))
  if (process.platform === 'darwin') app.quit()
  else window.close()
}

async function checkFolderActions(window) {
  const originalDialog = dialog.showOpenDialog
  const originalOpen = shell.openPath
  const selectedPath = path.join(storage, "User's créations 日本語")
  const settingsBefore = await (await fetch('http://127.0.0.1:8000/app-settings')).json()
  const choose = () => window.webContents.executeJavaScript('window.espImageServerDesktop.chooseImageLibrary()')
  try {
    dialog.showOpenDialog = async (parent, options) => {
      assert.equal(parent, window)
      assert.ok(options.properties.includes('openDirectory'))
      return { canceled: false, filePaths: [selectedPath] }
    }
    assert.equal(await choose(), selectedPath)
    dialog.showOpenDialog = async () => ({ canceled: true, filePaths: [] })
    assert.equal(await choose(), null)
    dialog.showOpenDialog = async () => { throw new Error('Folder dialog unavailable') }
    await assert.rejects(choose(), /Folder dialog unavailable/)
    const reveal = () => window.webContents.executeJavaScript(
      `window.espImageServerDesktop.revealImageLibrary(${JSON.stringify(selectedPath)})`)
    shell.openPath = async value => { assert.equal(value, selectedPath); return '' }
    assert.equal(await reveal(), '')
    shell.openPath = async () => 'No file manager available'
    assert.equal(await reveal(), 'No file manager available')
    const settingsAfter = await (await fetch('http://127.0.0.1:8000/app-settings')).json()
    assert.equal(settingsAfter.image_library_location, settingsBefore.image_library_location,
      'Choosing or opening a folder must not save or move the library')
    console.log('Folder IPC passed: selection, cancellation, errors, and unchanged saved library (native UI stubbed)')
  } finally {
    dialog.showOpenDialog = originalDialog
    shell.openPath = originalOpen
  }
}
await import('./main.mjs')
