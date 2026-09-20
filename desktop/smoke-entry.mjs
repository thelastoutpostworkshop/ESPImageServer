// Test-only entry point: exercise the real main module without production hooks.
import { app, BrowserWindow, dialog } from 'electron'
import assert from 'node:assert/strict'
import { writeFileSync } from 'node:fs'
import path from 'node:path'
import { setTimeout as delay } from 'node:timers/promises'

const storage = process.env.ESP_DESKTOP_SMOKE_STORAGE
if (!storage) throw new Error('Launch through npm run test:smoke.')
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
await import('./main.mjs')
