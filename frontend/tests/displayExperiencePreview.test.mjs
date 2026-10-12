import test from 'node:test'
import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import vm from 'node:vm'
import { displayExperienceDefaults, displayExperienceSettings } from '../src/displayExperience.js'

const source = await readFile(new URL('../src/App.vue', import.meta.url), 'utf8')
const previewFunctions = source.slice(source.indexOf('async function previewDisplayExperience('), source.indexOf('async function sendDisplaySdCardCommand('))

function deferred() {
  let resolve
  const promise = new Promise(complete => { resolve = complete })
  return { promise, resolve }
}

// Exercise the actual preview controls with a saved experience and a mocked
// command channel. No settings or playback command reaches a real board.
function setup({ experience = 'slideshow', legacy = false, onRequest } = {}) {
  let scope = legacy ? '' : '/displays/one'
  const requests = []
  const savedSettings = {
    ...displayExperienceDefaults(),
    offline_experience: experience,
    offline_experience_saved: true,
    slideshow_interval_ms: 25000,
    slideshow_order: 'oldest_first',
    orientation_filter_enabled: true,
    orientation_rotation: experience === 'video_loop' ? 270 : 90,
  }
  const ui = vm.createContext({
    activeDisplayOnline: { value: true },
    selectedDisplayEndpoint: suffix => scope + suffix,
    displayExperience: { value: { ...savedSettings } },
    reportedDisplayExperience: { value: { ...savedSettings } },
    displayExperienceIntervalSeconds: { value: 25 },
    displayExperiencePreviewing: { value: false },
    displayExperiencePreviewChanging: { value: false },
    displayExperienceSaving: { value: false },
    displayExperienceLoading: { value: false },
    displayExperienceError: { value: '' },
    displayExperienceStatus: { value: '' },
    sdCardDeletionActive: { value: false },
    requireDisplayCommandAvailable: () => {},
    displayExperienceSettings,
    fetch: async (url, options = {}) => {
      const request = {
        url,
        method: options.method || 'GET',
        body: options.body ? JSON.parse(options.body) : null,
        keepalive: options.keepalive,
      }
      requests.push(request)
      return await onRequest?.(request, ui) || { ok: true, json: async () => ({ id: 'preview-command' }) }
    },
  })
  vm.runInContext(previewFunctions, ui)
  return { ui, requests, savedSettings, selectDisplay: id => { scope = `/displays/${id}` } }
}

for (const experience of ['slideshow', 'video_loop']) {
  test(`a saved ${experience} can be previewed and restarted with the currently chosen settings`, async () => {
    const { ui, requests, savedSettings } = setup({ experience })
    await ui.previewDisplayExperience()
    assert.equal(ui.displayExperiencePreviewing.value, true)
    assert.equal(ui.displayExperiencePreviewChanging.value, false)
    assert.equal(requests.length, 1)
    assert.equal(requests[0].url, '/displays/one/display-experience/preview')
    assert.equal(requests[0].method, 'POST')
    assert.deepEqual(requests[0].body, {
      offline_experience: experience,
      slideshow_interval_ms: 25000,
      slideshow_order: 'oldest_first',
      orientation_filter_enabled: true,
      orientation_rotation: savedSettings.orientation_rotation,
    })

    ui.displayExperience.value.orientation_rotation = 180
    ui.displayExperience.value.slideshow_order = 'random'
    ui.displayExperienceIntervalSeconds.value = 7.5
    await ui.previewDisplayExperience()
    assert.equal(requests.length, 2)
    assert.deepEqual(requests[1].body, {
      offline_experience: experience,
      slideshow_interval_ms: 7500,
      slideshow_order: 'random',
      orientation_filter_enabled: true,
      orientation_rotation: 180,
    })
    assert.equal(ui.displayExperiencePreviewing.value, true)
    assert.equal(ui.reportedDisplayExperience.value.offline_experience_saved, true)
    assert.equal(ui.reportedDisplayExperience.value.orientation_rotation, savedSettings.orientation_rotation)
    assert.equal(ui.reportedDisplayExperience.value.slideshow_interval_ms, 25000)
  })
}

test('preview of a saved experience uses the legacy display endpoint when appropriate', async () => {
  const { ui, requests } = setup({ legacy: true })
  await ui.previewDisplayExperience()
  assert.equal(requests[0].url, '/display-experience/preview')
  assert.equal(ui.displayExperiencePreviewing.value, true)
})

test('an offline display cannot receive a preview or restart command', async () => {
  const { ui, requests } = setup()
  ui.activeDisplayOnline.value = false
  await ui.previewDisplayExperience()
  ui.displayExperiencePreviewing.value = true
  await ui.previewDisplayExperience()
  assert.equal(requests.length, 0)
  assert.equal(ui.displayExperiencePreviewChanging.value, false)
})

for (const busyRef of ['displayExperienceSaving', 'displayExperienceLoading']) {
  test(`preview cannot replace an in-flight ${busyRef === 'displayExperienceSaving' ? 'save' : 'settings load'}`, async () => {
    const { ui, requests } = setup()
    ui[busyRef].value = true
    await ui.previewDisplayExperience()
    assert.equal(requests.length, 0)
    assert.equal(ui.displayExperiencePreviewing.value, false)
  })
}

test('an in-flight preview request blocks another click until it completes', async () => {
  const response = deferred()
  const { ui, requests } = setup({ onRequest: () => response.promise })
  const starting = ui.previewDisplayExperience()
  assert.equal(ui.displayExperiencePreviewChanging.value, true)
  await ui.previewDisplayExperience()
  assert.equal(requests.length, 1)
  response.resolve({ ok: true })
  await starting
  assert.equal(ui.displayExperiencePreviewChanging.value, false)
  assert.equal(ui.displayExperiencePreviewing.value, true)
})

for (const previouslyPreviewing of [false, true]) {
  test(`a rejected ${previouslyPreviewing ? 'restart preserves the running preview' : 'start leaves preview inactive'}`, async () => {
    const { ui, requests } = setup({
      onRequest: async () => ({ ok: false, status: 409, json: async () => ({ detail: 'The display is busy saving media' }) }),
    })
    ui.displayExperiencePreviewing.value = previouslyPreviewing
    await ui.previewDisplayExperience()
    assert.equal(requests.length, 1)
    assert.equal(ui.displayExperiencePreviewing.value, previouslyPreviewing)
    assert.equal(ui.displayExperiencePreviewChanging.value, false)
    assert.match(ui.displayExperienceError.value, /display is busy saving media/)
  })
}

test('a preview response for the previous display does not start a preview on the newly selected display', async () => {
  const response = deferred()
  const { ui, requests, selectDisplay } = setup({ onRequest: () => response.promise })
  const starting = ui.previewDisplayExperience()
  selectDisplay('two')
  ui.displayExperienceStatus.value = 'Second display selected'
  response.resolve({ ok: true })
  await starting
  assert.equal(requests[0].url, '/displays/one/display-experience/preview')
  assert.equal(ui.displayExperiencePreviewing.value, false)
  assert.equal(ui.displayExperienceStatus.value, 'Second display selected')
})

test('an explicit stop sends a stop command and makes preview available again', async () => {
  const { ui, requests } = setup()
  await ui.previewDisplayExperience()
  await ui.stopDisplayExperiencePreview(true)
  assert.equal(requests[1].url, '/displays/one/display-experience/preview')
  assert.equal(requests[1].method, 'DELETE')
  assert.equal(requests[1].keepalive, true)
  assert.equal(ui.displayExperiencePreviewing.value, false)
  assert.equal(ui.displayExperiencePreviewChanging.value, false)
  assert.match(ui.displayExperienceStatus.value, /stopping/i)
  await ui.previewDisplayExperience()
  assert.equal(requests.length, 3)
  assert.equal(requests[2].method, 'POST')
})

test('automatic stop does not replace the current page status', async () => {
  const { ui, requests } = setup()
  ui.displayExperiencePreviewing.value = true
  ui.displayExperienceStatus.value = 'Display experience saved'
  await ui.stopDisplayExperiencePreview()
  assert.equal(requests.length, 1)
  assert.equal(requests[0].method, 'DELETE')
  assert.equal(ui.displayExperienceStatus.value, 'Display experience saved')
})

test('a rejected explicit stop keeps the preview controls active for retry', async () => {
  const { ui, requests } = setup({
    onRequest: async () => ({ ok: false, status: 409, json: async () => ({ detail: 'The display is busy saving media' }) }),
  })
  ui.displayExperiencePreviewing.value = true
  await ui.stopDisplayExperiencePreview(true)
  assert.equal(requests.length, 1)
  assert.equal(requests[0].method, 'DELETE')
  assert.equal(ui.displayExperiencePreviewing.value, true)
  assert.equal(ui.displayExperiencePreviewChanging.value, false)
  assert.match(ui.displayExperienceError.value, /Could not stop preview: The display is busy saving media/)
})

test('a rejected stop for the previous display does not restore preview or show an error on the newly selected display', async () => {
  const response = deferred()
  const { ui, requests, selectDisplay } = setup({ onRequest: () => response.promise })
  ui.displayExperiencePreviewing.value = true
  const stopping = ui.stopDisplayExperiencePreview(true)
  selectDisplay('two')
  ui.displayExperienceStatus.value = 'Second display selected'
  response.resolve({ ok: false, status: 409, json: async () => ({ detail: 'Old display is busy' }) })
  await stopping
  assert.equal(requests[0].url, '/displays/one/display-experience/preview')
  assert.equal(ui.displayExperiencePreviewing.value, false)
  assert.equal(ui.displayExperienceError.value, '')
  assert.equal(ui.displayExperienceStatus.value, 'Second display selected')
})

test('an inactive preview needs no stop command', async () => {
  const { ui, requests } = setup()
  await ui.stopDisplayExperiencePreview(true)
  assert.equal(requests.length, 0)
})

test('stop does not interrupt deletion which already owns the display command channel', async () => {
  const { ui, requests } = setup()
  ui.displayExperiencePreviewing.value = true
  ui.sdCardDeletionActive.value = true
  await ui.stopDisplayExperiencePreview(true)
  assert.equal(requests.length, 0)
  assert.equal(ui.displayExperiencePreviewing.value, true)
})
