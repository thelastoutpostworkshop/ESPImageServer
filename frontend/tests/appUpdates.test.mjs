import test from 'node:test'
import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import vm from 'node:vm'
import {
  appUpdateHttpsUrl, appUpdateInstallerLabel, appUpdateStatusMessage,
  createAppUpdatesController, useAppUpdates,
} from '../src/composables/useAppUpdates.js'

function deferred() {
  let resolve, reject
  const promise = new Promise((yes, no) => { resolve = yes; reject = no })
  return { promise, resolve, reject }
}
const response = body => ({ ok: true, json: async () => body })
function release(overrides = {}) {
  return {
    status: 'update_available', installed_version: '1.2.0', latest_version: '1.3.0', update_available: true,
    release_url: 'https://github.com/example/app/releases/tag/v1.3.0',
    download_url: 'https://github.com/example/app/releases/download/v1.3.0/setup.exe',
    checksum_url: 'https://github.com/example/app/releases/download/v1.3.0/setup.exe.sha256',
    platform: 'win32-x64', checked_at: '2026-10-07T12:00:00Z', checked_successfully: true, stale: false, error: '',
    ...overrides,
  }
}
function memoryStorage() {
  const values = new Map()
  return { getItem: key => values.get(key), setItem: (key, value) => values.set(key, value) }
}

test('automatic checks make no request when disabled, while a manual POST remains available', async () => {
  const requests = []
  const updates = createAppUpdatesController({ storage: null, fetchImpl: async (url, options) => {
    requests.push({ url, options }); return response(release())
  } })
  updates.setAutomaticEnabled(false)
  await updates.checkAutomatically()
  assert.equal(requests.length, 0)
  assert.equal(updates.result.value.status, 'disabled')
  await updates.checkManually()
  assert.equal(requests.length, 1)
  assert.equal(requests[0].url, '/app-updates/check')
  assert.equal(requests[0].options.method, 'POST')
  assert.equal(requests[0].options.cache, 'no-store')
  assert.equal(updates.result.value.latest_version, '1.3.0')
  assert.equal(updates.visibleUpdate.value, null)
  assert.equal(updates.checking.value, false)
})

test('repeated automatic polls share their in-flight GET', async () => {
  const pending = deferred(), requests = []
  const updates = createAppUpdatesController({ storage: null, fetchImpl: async (url, options) => {
    requests.push({ url, options }); return pending.promise
  } })
  updates.setAutomaticEnabled(true)
  const first = updates.checkAutomatically()
  assert.equal(updates.checking.value, true)
  assert.equal(updates.checkingManually.value, false)
  assert.equal(updates.checkAutomatically(), first)
  assert.equal(requests.length, 1)
  assert.equal(requests[0].url, '/app-updates')
  assert.equal(requests[0].options.method, 'GET')
  pending.resolve(response(release()))
  await first
  assert.equal(updates.visibleUpdate.value.latest_version, '1.3.0')
})

test('a manual check supersedes an automatic reply without older cleanup clearing manual loading', async () => {
  const automatic = deferred(), manual = deferred(), requests = []
  const updates = createAppUpdatesController({ storage: null, fetchImpl: async (url, options) => {
    requests.push({ url, options }); return url.endsWith('/check') ? manual.promise : automatic.promise
  } })
  updates.setAutomaticEnabled(true)
  const first = updates.checkAutomatically()
  const second = updates.checkManually()
  assert.equal(requests[0].options.signal.aborted, true)
  assert.equal(updates.checkManually(), second)
  automatic.resolve(response(release({ latest_version: '1.3.0' })))
  assert.equal(await first, null)
  assert.equal(updates.checkingManually.value, true)
  manual.resolve(response(release({ latest_version: '1.4.0' })))
  await second
  assert.equal(updates.result.value.latest_version, '1.4.0')
  assert.equal(updates.checking.value, false)
  assert.equal(requests.length, 2)
})

test('turning off automatic checks aborts the request and rejects its delayed successful reply', async () => {
  const pending = deferred()
  let signal
  const updates = createAppUpdatesController({ storage: null, fetchImpl: async (_url, options) => {
    signal = options.signal; return pending.promise
  } })
  updates.setAutomaticEnabled(true)
  const checking = updates.checkAutomatically()
  updates.setAutomaticEnabled(false)
  assert.equal(signal.aborted, true)
  assert.equal(updates.result.value.status, 'disabled')
  assert.equal(updates.checking.value, false)
  pending.resolve(response(release()))
  assert.equal(await checking, null)
  assert.equal(updates.result.value.status, 'disabled')
  assert.equal(updates.visibleUpdate.value, null)
})

test('turning off automatic checks leaves an explicit manual request running', async () => {
  const pending = deferred()
  let signal
  const updates = createAppUpdatesController({ storage: null, fetchImpl: async (_url, options) => {
    signal = options.signal; return pending.promise
  } })
  updates.setAutomaticEnabled(true)
  const checking = updates.checkManually()
  updates.setAutomaticEnabled(false)
  assert.equal(signal.aborted, false)
  assert.equal(updates.checkingManually.value, true)
  pending.resolve(response(release()))
  await checking
  assert.equal(updates.result.value.latest_version, '1.3.0')
  assert.equal(updates.visibleUpdate.value, null)
})

test('dismissal survives reload for one release and does not hide a newer release or About result', async () => {
  const storage = memoryStorage()
  let latest = '1.3.0'
  const fetchImpl = async () => response(release({ latest_version: latest }))
  const first = createAppUpdatesController({ storage, fetchImpl })
  first.setAutomaticEnabled(true)
  await first.checkAutomatically()
  first.dismissVersion()
  assert.equal(first.visibleUpdate.value, null)
  assert.equal(first.result.value.download_url.endsWith('setup.exe'), true)
  const reloaded = createAppUpdatesController({ storage, fetchImpl })
  reloaded.setAutomaticEnabled(true)
  await reloaded.checkAutomatically()
  assert.equal(reloaded.visibleUpdate.value, null)
  latest = '1.4.0'
  await reloaded.checkAutomatically()
  assert.equal(reloaded.visibleUpdate.value.latest_version, '1.4.0')
})

test('blocked browser storage still allows checks and session dismissal', async () => {
  const storage = { getItem: () => { throw new Error('Blocked') }, setItem: () => { throw new Error('Blocked') } }
  const updates = createAppUpdatesController({ storage, fetchImpl: async () => response(release()) })
  updates.setAutomaticEnabled(true)
  await updates.checkAutomatically()
  updates.dismissVersion()
  assert.equal(updates.visibleUpdate.value, null)
})

test('a refresh failure keeps a known update visible as stale and never claims the app is up to date', async () => {
  let failed = false
  const updates = createAppUpdatesController({ storage: null, fetchImpl: async () => {
    if (failed) throw new Error('Connection unavailable')
    return response(release())
  } })
  updates.setAutomaticEnabled(true)
  await updates.checkAutomatically()
  failed = true
  await updates.checkAutomatically()
  assert.equal(updates.result.value.status, 'error')
  assert.equal(updates.result.value.stale, true)
  assert.equal(updates.result.value.checked_successfully, false)
  assert.equal(updates.visibleUpdate.value.latest_version, '1.3.0')
  assert.equal(updates.statusMessage.value, 'Connection unavailable')
  assert.doesNotMatch(updates.statusMessage.value, /up to date/i)
})

test('unavailable/private feeds and unsupported platforms retain their distinct results', async () => {
  const updates = createAppUpdatesController({ storage: null, fetchImpl: async () => response(release({
    status: 'unsupported', download_url: null, checksum_url: null, platform: 'darwin-arm64',
  })) })
  updates.setAutomaticEnabled(true)
  await updates.checkManually()
  assert.equal(updates.visibleUpdate.value.download_url, null)
  assert.match(updates.statusMessage.value, /no installer for the computer/)
  assert.match(updates.result.value.release_url, /^https:/)
  assert.match(appUpdateStatusMessage({ status: 'unavailable' }), /private|published releases/)
  assert.doesNotMatch(appUpdateStatusMessage({ status: 'up_to_date', checked_successfully: false }), /up to date/i)
  assert.doesNotMatch(appUpdateStatusMessage({ status: 'up_to_date', checked_successfully: true, stale: true }), /up to date/i)
  assert.equal(appUpdateStatusMessage({ status: 'up_to_date', checked_successfully: true }), 'ESPImageServer is up to date.')
  assert.equal(appUpdateInstallerLabel('win32-x64'), 'Download Windows installer')
  assert.equal(appUpdateInstallerLabel('linux-x64'), 'Download Linux installer')
})

test('HTTP failures and malformed update responses do not become a successful check', async () => {
  for (const body of [{ ok: false, status: 503, json: async () => ({ detail: 'Public releases are unavailable' }) }, response({ status: 'unknown' })]) {
    const updates = createAppUpdatesController({ storage: null, fetchImpl: async () => body })
    await updates.checkManually()
    assert.equal(updates.result.value.status, 'error')
    assert.equal(updates.result.value.checked_successfully, false)
    assert.equal(updates.visibleUpdate.value, null)
    assert.equal(updates.checkingManually.value, false)
  }
})

test('download and release links accept only HTTPS URLs without embedded credentials', async () => {
  for (const value of ['javascript:alert(1)', 'http://example.com/file', 'https://token@example.com/file', '/relative']) assert.equal(appUpdateHttpsUrl(value), null)
  assert.equal(appUpdateHttpsUrl('https://example.com/release'), 'https://example.com/release')
  const updates = createAppUpdatesController({ storage: null, fetchImpl: async () => response(release({ download_url: 'javascript:alert(1)', release_url: 'http://example.com/' })) })
  await updates.checkManually()
  assert.equal(updates.result.value.download_url, null)
  assert.equal(updates.result.value.release_url, null)
})

test('a timed-out request leaves a retryable error and resets manual loading', async () => {
  const updates = createAppUpdatesController({ storage: null, requestTimeoutMs: 5, fetchImpl: (_url, options) => new Promise((_resolve, reject) => {
    options.signal.addEventListener('abort', () => reject(new Error('Aborted')), { once: true })
  }) })
  await updates.checkManually()
  assert.match(updates.statusMessage.value, /timed out/)
  assert.equal(updates.checking.value, false)
  assert.equal(updates.checkingManually.value, false)
})

test('the notice starts background checks, polls, and stops when its preference changes or it unmounts', async () => {
  const requests = [], timers = [], cleared = [], mounted = [], unmounted = []
  const controller = createAppUpdatesController({ storage: null, fetchImpl: async url => { requests.push(url); return response(release()) } })
  let lastCheck, preferenceChanged
  const updates = { ...controller, checkAutomatically: () => { lastCheck = controller.checkAutomatically(); return lastCheck } }
  const props = { enabled: true }
  const notice = await readFile(new URL('../src/components/AppUpdateNotice.vue', import.meta.url), 'utf8')
  const script = notice.slice(notice.indexOf('<script setup>') + '<script setup>'.length, notice.indexOf('</script>')).replace(/^import .*$/gm, '')
  vm.runInNewContext(script, {
    defineProps: () => props, useAppUpdates: () => updates,
    watch: (_source, callback) => { preferenceChanged = callback },
    onMounted: callback => mounted.push(callback), onUnmounted: callback => unmounted.push(callback),
    window: { setInterval: (callback, delay) => { timers.push({ callback, delay }); return 1 }, clearInterval: id => cleared.push(id) },
  })
  mounted[0]()
  await lastCheck
  assert.deepEqual(requests, ['/app-updates'])
  assert.equal(timers[0].delay, 60_000)
  await timers[0].callback()
  assert.equal(requests.length, 2)
  props.enabled = false
  preferenceChanged(false)
  await timers[0].callback()
  assert.equal(requests.length, 2)
  assert.equal(controller.result.value.status, 'disabled')
  unmounted[0]()
  assert.deepEqual(cleared, [1])
})

test('About and the global notice use the same controller', () => {
  assert.equal(useAppUpdates(), useAppUpdates())
})
