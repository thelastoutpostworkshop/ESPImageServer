import { computed, ref } from 'vue'

const dismissalStorageKey = 'esp-image-server.dismissed-app-update-versions'
const statuses = new Set(['update_available', 'up_to_date', 'unavailable', 'error', 'disabled', 'unsupported'])

function browserStorage() {
  try { return globalThis.localStorage || null } catch { return null }
}

export function appUpdateHttpsUrl(value) {
  if (typeof value !== 'string' || !value) return null
  try {
    const url = new URL(value)
    return url.protocol === 'https:' && !url.username && !url.password ? url.href : null
  } catch { return null }
}

function normalizeResult(value) {
  if (!value || !statuses.has(value.status)) throw new Error('The server returned an invalid app update response.')
  return {
    status: value.status,
    installed_version: typeof value.installed_version === 'string' ? value.installed_version : '',
    latest_version: typeof value.latest_version === 'string' ? value.latest_version : null,
    update_available: value.status !== 'disabled' && (value.update_available === true || value.status === 'update_available'),
    release_url: appUpdateHttpsUrl(value.release_url),
    download_url: appUpdateHttpsUrl(value.download_url),
    checksum_url: appUpdateHttpsUrl(value.checksum_url),
    platform: typeof value.platform === 'string' ? value.platform : '',
    checked_at: typeof value.checked_at === 'string' ? value.checked_at : null,
    checked_successfully: value.checked_successfully === true,
    error: typeof value.error === 'string' ? value.error : '',
    stale: value.stale === true,
  }
}

export function appUpdateStatusMessage(result) {
  if (!result) return 'Check for updates to find the latest app release.'
  if (result.status === 'disabled') return 'Automatic app update checks are off. You can still check manually.'
  if (result.status === 'unavailable') return result.error || 'App releases are unavailable. The repository may be private or have no published releases.'
  if (result.status === 'error') return result.error || 'Could not check app releases. Try again later.'
  if (result.status === 'unsupported') return result.update_available
    ? `Version ${result.latest_version} is available, but there is no installer for the computer running ESPImageServer.`
    : 'There is no app installer for the computer running ESPImageServer. See the release notes for available platforms.'
  if (result.status === 'update_available') return `ESPImageServer ${result.latest_version} is available.`
  if (result.status === 'up_to_date' && result.checked_successfully && !result.stale) return 'ESPImageServer is up to date.'
  return 'A successful update check is not available yet.'
}

export function appUpdateInstallerLabel(platform) {
  if (platform === 'win32-x64') return 'Download Windows installer'
  if (platform === 'linux-x64') return 'Download Linux installer'
  return 'Download installer'
}

// One controller is shared by the global notice and About. Injectable network
// and storage access let lifecycle tests run without contacting GitHub.
export function createAppUpdatesController({ fetchImpl = (...args) => fetch(...args), storage = browserStorage(), requestTimeoutMs = 30_000 } = {}) {
  const result = ref(null)
  const checking = ref(false)
  const checkingManually = ref(false)
  const automaticEnabled = ref(false)
  let storedDismissals = []
  try {
    const stored = JSON.parse(storage?.getItem(dismissalStorageKey) || '[]')
    if (Array.isArray(stored)) storedDismissals = stored.filter(version => typeof version === 'string')
  } catch { /* Storage may be blocked or contain an older value. */ }
  const dismissedVersions = ref(new Set(storedDismissals))
  const visibleUpdate = computed(() => automaticEnabled.value && result.value?.update_available && result.value.latest_version
    && !dismissedVersions.value.has(result.value.latest_version) ? result.value : null)
  const statusMessage = computed(() => appUpdateStatusMessage(result.value))
  let requestSequence = 0
  let activeRequest = null

  function stopRequest() {
    if (!activeRequest) return
    activeRequest.controller.abort()
    clearTimeout(activeRequest.timeout)
    activeRequest = null
    ++requestSequence
    checking.value = false
    checkingManually.value = false
  }

  function setAutomaticEnabled(enabled) {
    automaticEnabled.value = enabled === true
    if (automaticEnabled.value) return
    if (activeRequest && !activeRequest.manual) stopRequest()
    // Turning off background checks must not cancel an explicit manual check.
    if (!activeRequest?.manual) result.value = normalizeResult({ status: 'disabled', installed_version: result.value?.installed_version })
  }

  function dismissVersion(version = result.value?.latest_version) {
    if (typeof version !== 'string' || !version) return
    dismissedVersions.value = new Set([...dismissedVersions.value, version])
    try { storage?.setItem(dismissalStorageKey, JSON.stringify([...dismissedVersions.value].slice(-50))) } catch { /* Keep dismissal for this session. */ }
  }

  function check(manual) {
    if (!manual && !automaticEnabled.value) return Promise.resolve(null)
    if (activeRequest && (!manual || activeRequest.manual)) return activeRequest.promise
    if (activeRequest) stopRequest()
    const request = { sequence: ++requestSequence, controller: new AbortController(), manual, timeout: null, promise: null }
    activeRequest = request
    checking.value = true
    checkingManually.value = manual
    const canPublish = () => request.sequence === requestSequence && (manual || automaticEnabled.value)
    request.promise = (async () => {
      request.timeout = setTimeout(() => request.controller.abort(), requestTimeoutMs)
      try {
        const response = await fetchImpl(manual ? '/app-updates/check' : '/app-updates', {
          method: manual ? 'POST' : 'GET', cache: 'no-store', signal: request.controller.signal,
        })
        if (!response.ok) {
          const body = await response.json().catch(() => ({}))
          throw new Error(typeof body.detail === 'string' ? body.detail : `Request failed (${response.status})`)
        }
        const next = normalizeResult(await response.json())
        if (!canPublish()) return null
        if (request.controller.signal.aborted) throw new Error('The update check timed out. Try again.')
        result.value = next
        return next
      } catch (error) {
        if (!canPublish()) return null
        result.value = normalizeResult({
          ...result.value, status: 'error', checked_successfully: false,
          stale: Boolean(result.value?.checked_at || result.value?.update_available),
          error: request.controller.signal.aborted ? 'The update check timed out. Try again.' : String(error.message || error),
        })
        return result.value
      } finally {
        clearTimeout(request.timeout)
        if (request.sequence === requestSequence) {
          activeRequest = null
          checking.value = false
          checkingManually.value = false
        }
      }
    })()
    return request.promise
  }

  return { result, checking, checkingManually, automaticEnabled, visibleUpdate, statusMessage, dismissedVersions,
    setAutomaticEnabled, dismissVersion, checkAutomatically: () => check(false), checkManually: () => check(true) }
}

let sharedController
export function useAppUpdates() {
  sharedController ||= createAppUpdatesController()
  return sharedController
}
