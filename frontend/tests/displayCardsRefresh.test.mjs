import test from 'node:test'
import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import vm from 'node:vm'
import { computed, ref } from 'vue'
import { sessionDisplayId } from '../src/displaySession.js'

const source = await readFile(new URL('../src/App.vue', import.meta.url), 'utf8')
const start = source.indexOf('let displayCardSdRequest = null')
const end = source.indexOf('let displayRequest = null', start)
assert.ok(start >= 0 && end > start, 'Missing production display-card refresh boundary')
const refreshCode = source.slice(start, end)
const registryEnd = source.indexOf('async function loadDisplaySettings()', end)
assert.ok(registryEnd > end, 'Missing production display registry refresh boundary')
const registryCode = source.slice(start, registryEnd)

function deferred() {
  let resolve, reject
  const promise = new Promise((yes, no) => { resolve = yes; reject = no })
  return { promise, resolve, reject }
}

const response = value => ({ ok: true, json: async () => value })
const report = (version, filename = 'saved.jpg') => ({
  available: true, report_version: version, files: [{ name: filename }],
})

// Run the production refresh with real Vue refs and controlled responses.
// Every request is a stub; no display commands or hardware are involved.
function setup(targets = [{ id: 'one' }, { id: 'two' }], registry = false) {
  const requests = []
  const ui = vm.createContext({
    AbortSignal,
    displays: ref(targets),
    displayCardSdStates: ref({}),
    displayCardsLoading: ref(false),
    activeDisplayId: ref(targets[0]?.id || ''),
    legacyDisplay: ref(null),
    page: ref('workspace'),
    displaySelectionInitialized: true,
    displayConnectedMessage: ref(''),
    displayConnectedSnackbar: ref(false),
    sessionDisplayId,
    request: async () => assert.fail('Unexpected display-card request'),
    fetch: (url, options) => {
      requests.push({ url, options })
      return ui.request(url, options)
    },
  })
  ui.display = computed(() => {
    const selected = ui.displays.value.find(target => target.id === ui.activeDisplayId.value)
    return selected ? { ...selected, connected: true } : ui.legacyDisplay.value
  })
  vm.runInContext(registry ? registryCode : refreshCode, ui)
  return { ui, requests }
}

test('only the initial SD-report batch shows loading, until every response finishes', async () => {
  const { ui, requests } = setup(), first = deferred(), second = deferred()
  ui.request = url => url.includes('/one/') ? first.promise : second.promise
  const loading = ui.loadDisplayCardSdStates()
  assert.equal(ui.displayCardsLoading.value, true)
  first.resolve(response(report(1)))
  await new Promise(resolve => setImmediate(resolve))
  assert.equal(ui.displayCardsLoading.value, true)
  second.resolve(response(report(2)))
  await loading
  assert.equal(ui.displayCardsLoading.value, false)
  assert.equal(ui.displayCardSdStates.value.one.report_version, 1)
  assert.equal(ui.displayCardSdStates.value.two.report_version, 2)
  assert.ok(requests.every(({ options }) => options.cache === 'no-store' && options.signal instanceof AbortSignal))
})

test('a background refresh keeps cards and their cached SD reports visible while pending', async () => {
  const { ui } = setup([{ id: 'one', name: 'First screen' }])
  ui.request = async () => response(report(1, 'old.jpg'))
  await ui.loadDisplayCardSdStates()
  const cards = ui.displays.value, cached = ui.displayCardSdStates.value.one
  const pending = deferred()
  ui.request = () => pending.promise
  const refresh = ui.loadDisplayCardSdStates()
  assert.equal(ui.displayCardsLoading.value, false)
  assert.equal(ui.displays.value, cards)
  assert.equal(ui.displayCardSdStates.value.one, cached)
  pending.resolve(response(report(2, 'new.jpg')))
  await refresh
  assert.equal(ui.displayCardsLoading.value, false)
  assert.equal(ui.displays.value, cards)
  assert.equal(ui.displayCardSdStates.value.one.files[0].name, 'new.jpg')
})

test('overlapping refresh calls share a batch and later polls can start another batch', async () => {
  const { ui, requests } = setup([{ id: 'screen A/2' }]), pending = deferred()
  ui.request = () => pending.promise
  const first = ui.loadDisplayCardSdStates(), overlapping = ui.loadDisplayCardSdStates()
  assert.equal(overlapping, first)
  assert.deepEqual(requests.map(({ url }) => url), ['/displays/screen%20A%2F2/display-sd-card'])
  pending.resolve(response(report(1)))
  await Promise.all([first, overlapping])
  ui.request = async () => response(report(2))
  await ui.loadDisplayCardSdStates()
  assert.equal(requests.length, 2)
  assert.equal(ui.displayCardsLoading.value, false)
  assert.equal(ui.displayCardSdStates.value['screen A/2'].report_version, 2)
})

for (const failure of ['HTTP error', 'network rejection', 'invalid JSON']) {
  test(`a ${failure} preserves that display's report while successful siblings update`, async () => {
    const { ui } = setup()
    ui.request = async () => response(report(1))
    await ui.loadDisplayCardSdStates()
    const cached = ui.displayCardSdStates.value.one
    ui.request = async url => {
      if (url.includes('/two/')) return response({ available: false, report_version: 2, files: [] })
      if (failure === 'HTTP error') return { ok: false, status: 503 }
      if (failure === 'network rejection') throw new Error('Connection unavailable')
      return { ok: true, json: async () => { throw new SyntaxError('Invalid JSON') } }
    }
    await ui.loadDisplayCardSdStates()
    assert.equal(ui.displayCardSdStates.value.one, cached)
    assert.equal(ui.displayCardSdStates.value.two.available, false)
    assert.equal(ui.displayCardSdStates.value.two.report_version, 2)
    assert.equal(ui.displayCardsLoading.value, false)
    ui.request = async () => response(report(3))
    await ui.loadDisplayCardSdStates()
    assert.equal(ui.displayCardSdStates.value.one.report_version, 3)
  })
}

test('a delayed batch cannot restore removed displays or clear a newly added display report', async () => {
  const { ui, requests } = setup()
  ui.request = async () => response(report(1))
  await ui.loadDisplayCardSdStates()
  const pending = deferred()
  ui.request = () => pending.promise
  const refresh = ui.loadDisplayCardSdStates()
  ui.displays.value = [{ id: 'two' }, { id: 'three' }]
  ui.displayCardSdStates.value.three = report(7, 'new-display.jpg')
  const thirdReport = ui.displayCardSdStates.value.three
  assert.equal(ui.loadDisplayCardSdStates(), refresh)
  pending.resolve(response(report(2, 'delayed.jpg')))
  await refresh
  assert.equal('one' in ui.displayCardSdStates.value, false)
  assert.equal(ui.displayCardSdStates.value.two.report_version, 2)
  assert.equal(ui.displayCardSdStates.value.three, thirdReport)
  ui.request = async () => response(report(8))
  await ui.loadDisplayCardSdStates()
  assert.equal(requests.at(-1).url, '/displays/three/display-sd-card')
  assert.equal(ui.displayCardSdStates.value.three.report_version, 8)
})

test('removing every display while a batch is pending leaves no stale reports after completion', async () => {
  const { ui, requests } = setup([{ id: 'one' }]), pending = deferred()
  ui.displayCardSdStates.value = { one: report(1) }
  ui.request = () => pending.promise
  const refresh = ui.loadDisplayCardSdStates()
  ui.displays.value = []
  assert.equal(ui.loadDisplayCardSdStates(), refresh)
  pending.resolve(response(report(2)))
  await refresh
  assert.deepEqual(Object.keys(ui.displayCardSdStates.value), [])
  assert.equal(ui.displayCardsLoading.value, false)
  await ui.loadDisplayCardSdStates()
  assert.equal(requests.length, 1)
})

test('overlapping registry polls share requests and a later poll can refresh again', async () => {
  const { ui, requests } = setup([{ id: 'one', online: true }], true)
  const registered = deferred(), legacy = deferred()
  const cards = ui.displays.value
  ui.request = url => url === '/displays' ? registered.promise : legacy.promise
  const first = ui.loadDisplay(), overlapping = ui.loadDisplay()
  assert.equal(overlapping, first)
  assert.deepEqual(requests.map(({ url }) => url), ['/displays', '/display'])
  assert.equal(ui.displays.value, cards)
  registered.resolve(response([{ id: 'one', online: true, name: 'Updated screen' }]))
  legacy.resolve(response(null))
  await Promise.all([first, overlapping])
  assert.equal(ui.displays.value[0].name, 'Updated screen')
  ui.request = async url => response(url === '/displays' ? [{ id: 'one', online: true, name: 'Newest screen' }] : null)
  await ui.loadDisplay()
  assert.equal(requests.length, 4)
  assert.equal(ui.displays.value[0].name, 'Newest screen')
  assert.equal(ui.activeDisplayId.value, 'one')
})

for (const failure of ['HTTP error', 'network rejection', 'invalid JSON', 'malformed display list']) {
  test(`a registry ${failure} preserves profiles, selection, and cached card reports`, async () => {
    const { ui } = setup([{ id: 'one', online: true }, { id: 'two', online: false }], true)
    ui.activeDisplayId.value = 'two'
    ui.legacyDisplay.value = { connected: true, name: 'Last legacy display' }
    ui.displayCardSdStates.value = { one: report(1), two: report(2) }
    const cards = ui.displays.value, reports = ui.displayCardSdStates.value, legacy = ui.legacyDisplay.value
    ui.request = async url => {
      if (url === '/display') return response(null)
      if (failure === 'HTTP error') return { ok: false, status: 503 }
      if (failure === 'network rejection') throw new Error('Server unreachable')
      if (failure === 'invalid JSON') return { ok: true, json: async () => { throw new SyntaxError('Invalid JSON') } }
      return response({ invalid: 'not a display list' })
    }
    await ui.loadDisplay()
    assert.equal(ui.displays.value, cards)
    assert.equal(ui.displayCardSdStates.value, reports)
    assert.equal(ui.legacyDisplay.value, legacy)
    assert.equal(ui.activeDisplayId.value, 'two')
    assert.equal(ui.displaySelectionInitialized, true)
    assert.equal(ui.displayConnectedSnackbar.value, false)
    ui.request = async url => response(url === '/displays' ? [{ id: 'two', online: true, name: 'Recovered screen' }] : null)
    await ui.loadDisplay()
    assert.equal(ui.displays.value[0].name, 'Recovered screen')
    assert.equal(ui.activeDisplayId.value, 'two')
  })
}

for (const failure of ['network rejection', 'HTTP error', 'invalid JSON']) {
  test(`a legacy ${failure} cannot discard a valid registered-display update`, async () => {
    const { ui } = setup([{ id: 'one', online: true }], true)
    ui.legacyDisplay.value = { connected: true, name: 'Old legacy display' }
    ui.request = async url => {
      if (url === '/displays') return response([{ id: 'new', online: true, name: 'New screen' }])
      if (failure === 'network rejection') throw new Error('Legacy endpoint unavailable')
      if (failure === 'HTTP error') return { ok: false, status: 503 }
      return { ok: true, json: async () => { throw new SyntaxError('Invalid legacy JSON') } }
    }
    await ui.loadDisplay()
    assert.equal(ui.displays.value[0].id, 'new')
    assert.equal(ui.activeDisplayId.value, 'new')
    assert.equal(ui.legacyDisplay.value, null)
  })
}

test('an accepted empty registry clears removed cards and selection despite a failed legacy request', async () => {
  const { ui, requests } = setup([{ id: 'one', online: true }], true)
  ui.page.value = 'displays'
  ui.displayCardSdStates.value = { one: report(1) }
  ui.request = async url => {
    if (url === '/displays') return response([])
    throw new Error('Legacy endpoint unavailable')
  }
  await ui.loadDisplay()
  assert.equal(ui.displays.value.length, 0)
  assert.equal(ui.activeDisplayId.value, '')
  assert.deepEqual(Object.keys(ui.displayCardSdStates.value), [])
  assert.equal(requests.length, 2)
})
