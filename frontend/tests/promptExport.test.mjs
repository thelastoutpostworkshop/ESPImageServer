import test from 'node:test'
import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import vm from 'node:vm'

const source = await readFile(new URL('../src/App.vue', import.meta.url), 'utf8')
const start = source.indexOf('async function exportAllPrompts()')
const end = source.indexOf('async function refreshCreationLibrarySdCardStatus()', start)
assert.ok(start >= 0 && end > start, 'Missing prompt export function')
const exportCode = source.slice(start, end)
function deferred() {
  let resolve, reject
  const promise = new Promise((yes, no) => { resolve = yes; reject = no })
  return { promise, resolve, reject }
}
// Deliberately expose a local date one day before the UTC date. Filename tests
// must pass regardless of the test host's timezone.
class LocalMidnightDate extends Date {
  constructor() { super('2026-10-07T00:30:00Z') }
  getFullYear() { return 2026 }
  getMonth() { return 9 }
  getDate() { return 6 }
}
function setup({ clickError } = {}) {
  const requests = [], createdUrls = [], revokedUrls = [], timers = [], appended = []
  let clicks = 0, removals = 0
  const link = { href: '', download: '', click() { ++clicks; if (clickError) throw new Error(clickError) }, remove() { ++removals } }
  const file = { contents: 'Prompt: café\nNegative prompt: none\nSeed: 0' }
  const ui = vm.createContext({
    exportingAllPrompts: { value: false }, promptExportError: { value: 'Old error' }, status: { value: '' },
    Date: LocalMidnightDate,
    AbortSignal: { timeout: milliseconds => ({ timeoutMs: milliseconds }) },
    URL: {
      createObjectURL: blob => { createdUrls.push(blob); return 'blob:prompt-export' },
      revokeObjectURL: url => revokedUrls.push(url),
    },
    document: { createElement: tag => { assert.equal(tag, 'a'); return link }, body: { appendChild: anchor => appended.push(anchor) } },
    window: { setTimeout: (callback, delay) => { timers.push({ callback, delay }); return timers.length } },
    fetch: async (url, options) => { requests.push({ url, options }); return { ok: true, blob: async () => file } },
    selectedDisplayEndpoint: () => assert.fail('Export must include every display and ignore gallery filters'),
    creationModelFilter: { value: 'only-one-model' }, creationDisplayFilter: { value: 'only-one-display' },
  })
  vm.runInContext(exportCode, ui)
  return { ui, file, link, requests, createdUrls, revokedUrls, timers, appended,
    get clicks() { return clicks }, get removals() { return removals } }
}

test('export stays pending through response and blob reads and ignores repeat clicks', async () => {
  const state = setup(), response = deferred(), blob = deferred()
  state.ui.fetch = async (url, options) => { state.requests.push({ url, options }); return response.promise }
  const first = state.ui.exportAllPrompts()
  assert.equal(state.ui.exportingAllPrompts.value, true)
  assert.equal(state.ui.promptExportError.value, '')
  await state.ui.exportAllPrompts()
  assert.equal(state.requests.length, 1)
  response.resolve({ ok: true, blob: async () => blob.promise })
  await Promise.resolve()
  assert.equal(state.ui.exportingAllPrompts.value, true)
  await state.ui.exportAllPrompts()
  assert.equal(state.requests.length, 1)
  blob.resolve(state.file)
  await first
  assert.equal(state.ui.exportingAllPrompts.value, false)
  assert.equal(state.clicks, 1)
})

test('export downloads fresh unfiltered text using the local date and cleans up temporary resources', async () => {
  const state = setup()
  await state.ui.exportAllPrompts()
  assert.equal(state.requests.length, 1)
  assert.equal(state.requests[0].url, '/creation-library/prompts.txt')
  assert.equal(state.requests[0].options.cache, 'no-store')
  assert.equal(state.requests[0].options.headers.Accept, 'text/plain')
  assert.equal(state.link.download, 'ESPImageServer-prompts-2026-10-06.txt')
  assert.equal(state.link.href, 'blob:prompt-export')
  assert.deepEqual(state.createdUrls, [state.file])
  assert.deepEqual(state.appended, [state.link])
  assert.equal(state.clicks, 1)
  assert.equal(state.removals, 1)
  assert.deepEqual(state.revokedUrls, [])
  assert.equal(state.timers.length, 1)
  assert.equal(state.timers[0].delay, 1000)
  state.timers[0].callback()
  assert.deepEqual(state.revokedUrls, ['blob:prompt-export'])
  assert.match(state.ui.status.value, /All saved creation prompts and settings exported/)
})

for (const failure of ['network', 'HTTP', 'blob']) {
  test(failure + ' failure shows the export error without downloading an empty file', async () => {
    const state = setup()
    state.ui.fetch = async () => {
      if (failure === 'network') throw new Error('Connection interrupted')
      if (failure === 'HTTP') return { ok: false, status: 503, json: async () => ({ detail: 'Library is unavailable' }), blob: async () => assert.fail('Must not download failed response') }
      return { ok: true, blob: async () => { throw new Error('Text could not be read') } }
    }
    await state.ui.exportAllPrompts()
    assert.match(state.ui.promptExportError.value, /Could not export prompts/)
    assert.equal(state.ui.exportingAllPrompts.value, false)
    assert.equal(state.ui.status.value, '')
    assert.equal(state.clicks, 0)
    assert.deepEqual(state.createdUrls, [])
    assert.deepEqual(state.appended, [])
    assert.deepEqual(state.timers, [])
  })
}

test('an HTTP error with an unreadable body still reports its status and permits a later retry', async () => {
  const state = setup(), originalFetch = state.ui.fetch
  state.ui.fetch = async () => ({ ok: false, status: 500, json: async () => { throw new Error('Invalid JSON') } })
  await state.ui.exportAllPrompts()
  assert.match(state.ui.promptExportError.value, /Request failed \(500\)/)
  state.ui.fetch = originalFetch
  await state.ui.exportAllPrompts()
  assert.equal(state.ui.promptExportError.value, '')
  assert.equal(state.clicks, 1)
})

test('a failed download click still removes its anchor and releases its object URL', async () => {
  const state = setup({ clickError: 'Download is unavailable' })
  await state.ui.exportAllPrompts()
  assert.match(state.ui.promptExportError.value, /Download is unavailable/)
  assert.equal(state.ui.exportingAllPrompts.value, false)
  assert.equal(state.ui.status.value, '')
  assert.equal(state.removals, 1)
  assert.equal(state.timers.length, 1)
  state.timers[0].callback()
  assert.deepEqual(state.revokedUrls, ['blob:prompt-export'])
})
