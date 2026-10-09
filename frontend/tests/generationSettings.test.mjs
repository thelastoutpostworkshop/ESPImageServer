import test from 'node:test'
import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import vm from 'node:vm'
import { computed, nextTick, ref, watch } from 'vue'

const source = await readFile(new URL('../src/App.vue', import.meta.url), 'utf8')
const imageKey = 'esp-image-server.generation-settings'
const videoKey = 'esp-image-server.video-generation-settings'
const distilled = 'ltx-2b-0.9.6-distilled'
const quality = 'ltx-2b-0.9.6-dev'
const wan = 'wan-2.1-t2v-1.3b'
const imageCatalog = [
  { id: 'Lykon/dreamshaper-8', active: true, default_steps: 25, minimum_steps: 1, maximum_steps: 100 },
  { id: 'segmind/SSD-1B', active: false, default_steps: 20, minimum_steps: 1, maximum_steps: 100 },
]
const videoCatalog = [
  { id: distilled, supports_image: true, supports_negative_prompt: false },
  { id: quality, supports_image: true, supports_negative_prompt: true },
  { id: wan, supports_image: false, supports_negative_prompt: true },
]

function slice(start, end) {
  const from = source.indexOf(start), to = source.indexOf(end, from + start.length)
  assert.ok(from >= 0 && to > from, `Missing production boundary: ${start} / ${end}`)
  return source.slice(from, to)
}

function declaration(name) {
  const match = source.match(new RegExp(`^const ${name} = .*`, 'm'))
  assert.ok(match, `Missing production state: ${name}`)
  return match[0]
}

function storage(image = {}, video = {}) {
  const values = new Map([[imageKey, JSON.stringify(image)], [videoKey, JSON.stringify(video)]])
  return {
    getItem: key => values.get(key) ?? null,
    setItem: (key, value) => { values.set(key, value) },
    read: key => JSON.parse(values.get(key) || '{}'),
  }
}

const stateNames = [
  'prompt', 'negativePrompt', 'steps', 'seed', 'randomizeImageSeed', 'activeModelId',
  'videoSourceImage', 'videoPrompt', 'videoNegativePrompt', 'videoSeed', 'randomizeVideoSeed',
  'videoFrames', 'videoFps', 'videoDurationPresetSeconds', 'showAdvancedVideoFrames', 'videoSteps',
  'videoModelId', 'videoStage', 'videoError',
]

// Execute the production loaders and Vue watchers. The fixtures never contact
// the local server, a model repository, or generation jobs.
function setup(t, localStorage = storage(), options = {}) {
  const disposers = [], requests = []
  const ui = vm.createContext({
    ref, computed, nextTick, AbortController, AbortSignal, Blob,
    watch: (...args) => { const stop = watch(...args); disposers.push(stop); return stop },
    window: { localStorage },
    createRandomSeed: () => 42,
    models: ref([]), availableVideoModels: ref(options.videoCatalog ?? videoCatalog),
    savedImages: ref(options.savedImages ?? []),
    fetch: async (url, request) => {
      requests.push({ url, request })
      if (options.fetch) return options.fetch(url, request)
      if (url === '/models') return { ok: true, json: async () => imageCatalog }
      if (url === '/video-models') return { ok: true, json: async () => videoCatalog }
      throw new Error(`Unexpected request in generation settings test: ${url}`)
    },
  })
  const bootstrap = [
    declaration('generationSettingsKey'), declaration('videoGenerationSettingsKey'), declaration('videoModelIds'),
    slice('function loadGenerationSettings()', 'const savedGenerationSettings'),
    declaration('savedGenerationSettings'), declaration('savedVideoGenerationSettings'),
    ...stateNames.map(declaration),
    slice('const videoDurationPresets =', 'const videoModels ='),
    slice('const selectedVideoModelCapabilities =', 'const rotationOptions ='),
    slice('watch([prompt,', 'watch(metadataPanePinned,'),
    slice('async function loadModels()', 'function confirmRemoveImageModel('),
    slice('function selectModelById(', 'function chooseRandomSeed('),
    slice('async function restoreVideoSourceImage()', 'async function loadSavedVideos('),
    `state = { ${stateNames.join(', ')} }`,
  ]
  vm.runInContext(bootstrap.join('\n'), ui)
  t.after(() => disposers.forEach(stop => stop()))
  return { ui, state: ui.state, requests, localStorage }
}

function stateSnapshot(state) {
  return Object.fromEntries(stateNames.map(name => [name,
    name === 'videoSourceImage' ? state[name].value?.id ?? null : state[name].value]))
}

test('complete image and video form choices survive save, reopen, and asynchronous catalog refresh', async t => {
  const drafts = storage(
    { modelId: 'segmind/SSD-1B', prompt: 'Saved image prompt', negativePrompt: 'avoid text', steps: 37, seed: 7, randomizeSeed: false },
    { modelId: quality, prompt: 'Saved video prompt', negativePrompt: '', frames: 73, fps: 15, steps: 35, seed: 8,
      randomizeSeed: false, sourceImageId: 'first-frame.jpg', showAdvancedFrames: true, durationPresetSeconds: null },
  )
  const first = setup(t, drafts)
  first.state.prompt.value = 'A café in the rain'
  first.state.negativePrompt.value = 'blurry\nletters'
  first.state.steps.value = 41
  first.state.seed.value = 0
  first.state.randomizeImageSeed.value = true
  first.state.videoPrompt.value = 'The camera pans slowly'
  first.state.videoNegativePrompt.value = 'flickering'
  first.state.videoSteps.value = 40
  first.state.videoSeed.value = 0
  first.state.randomizeVideoSeed.value = true
  await nextTick()
  const expected = stateSnapshot(first.state)
  const reopened = setup(t, drafts, { videoCatalog: [] })
  assert.deepEqual(stateSnapshot(reopened.state), expected)
  await Promise.all([reopened.ui.loadModels(), reopened.ui.loadVideoModels()])
  await nextTick()
  assert.deepEqual(stateSnapshot(reopened.state), expected)
  assert.equal(drafts.read(imageKey).steps, 41)
  assert.equal(drafts.read(videoKey).steps, 40)
  assert.deepEqual(reopened.requests.map(request => request.url).sort(), ['/models', '/video-models'])
})

for (const seed of [0, null, '']) {
  test(`image and video seed ${JSON.stringify(seed)} retain their explicit choice after reopening`, async t => {
    const drafts = storage({ seed, steps: 31 }, { seed, modelId: quality, steps: 35 })
    const first = setup(t, drafts)
    const expected = seed === 0 ? 0 : ''
    assert.equal(first.state.seed.value, expected)
    assert.equal(first.state.videoSeed.value, expected)
    first.state.prompt.value = 'Trigger image draft save'
    first.state.videoPrompt.value = 'Trigger video draft save'
    await nextTick()
    assert.equal(drafts.read(imageKey).seed, seed === 0 ? 0 : null)
    assert.equal(drafts.read(videoKey).seed, seed === 0 ? 0 : null)
    const reopened = setup(t, drafts)
    assert.equal(reopened.state.seed.value, expected)
    assert.equal(reopened.state.videoSeed.value, expected)
  })
}

test('advanced frames and an explicitly cleared duration preset remain selected after reopening', async t => {
  const drafts = storage({}, { modelId: distilled, frames: 25, fps: 8, durationPresetSeconds: null, showAdvancedFrames: true })
  const first = setup(t, drafts)
  assert.equal(first.state.videoDurationPresetSeconds.value, null)
  assert.equal(first.state.showAdvancedVideoFrames.value, true)
  first.state.videoFrames.value = 49
  await nextTick()
  const reopened = setup(t, drafts)
  assert.equal(reopened.state.videoFrames.value, 49)
  assert.equal(reopened.state.videoDurationPresetSeconds.value, null)
  assert.equal(reopened.state.showAdvancedVideoFrames.value, true)
})

test('legacy video drafts infer a matching duration preset without changing stored frames or fps', t => {
  const run = setup(t, storage({}, { modelId: distilled, frames: 25, fps: 8 }))
  assert.equal(run.state.videoDurationPresetSeconds.value, 3)
  assert.equal(run.state.videoFrames.value, 25)
  assert.equal(run.state.videoFps.value, 8)
})

test('saved duration preset survives reopening and updates frames when fps changes', async t => {
  const drafts = storage({}, { modelId: distilled, frames: 17, fps: 8, durationPresetSeconds: 2, showAdvancedFrames: false })
  const first = setup(t, drafts)
  assert.equal(first.state.videoDurationPresetSeconds.value, 2)
  first.state.videoFps.value = 12
  await nextTick()
  const reopened = setup(t, drafts)
  assert.equal(reopened.state.videoDurationPresetSeconds.value, 2)
  assert.equal(reopened.state.videoFrames.value, 25)
  assert.equal(reopened.state.videoFps.value, 12)
})

test('source image present in the gallery restores without another request', async t => {
  const record = { id: 'first-frame.jpg', metadata: { prompt: 'Saved first frame' } }
  const run = setup(t, storage({}, { modelId: quality, sourceImageId: record.id }), { savedImages: [record] })
  await run.ui.restoreVideoSourceImage()
  assert.equal(run.state.videoSourceImage.value.id, record.id)
  assert.equal(run.state.videoSourceImage.value.metadata.prompt, 'Saved first frame')
  assert.equal(run.requests.length, 0)
})

test('source image outside the latest gallery page restores by ID without generation', async t => {
  const run = setup(t, storage({}, { modelId: quality, sourceImageId: 'older first frame.jpg' }), {
    savedImages: Array.from({ length: 50 }, (_, index) => ({ id: `newer-${index}.jpg` })),
    fetch: async () => ({ ok: true, status: 200, blob: async () => new Blob() }),
  })
  await run.ui.restoreVideoSourceImage()
  assert.equal(run.state.videoSourceImage.value.id, 'older first frame.jpg')
  assert.equal(run.requests.length, 1)
  assert.equal(run.requests[0].url, '/saved-images/older%20first%20frame.jpg/thumbnail')
  assert.equal(run.requests[0].request.cache, 'no-store')
  assert.equal(run.requests[0].request.method ?? 'GET', 'GET')
})

test('a missing source image is cleared from the current form and persisted draft', async t => {
  const drafts = storage({}, { modelId: quality, sourceImageId: 'deleted-frame.jpg' })
  const run = setup(t, drafts, { fetch: async () => ({ ok: false, status: 404 }) })
  await run.ui.restoreVideoSourceImage()
  await nextTick()
  assert.equal(run.state.videoSourceImage.value, null)
  assert.equal(drafts.read(videoKey).sourceImageId, null)
})

for (const failure of ['offline', 'server error']) {
  test(`source-image ${failure} retains the last selected ID for a later retry`, async t => {
    const drafts = storage({}, { modelId: quality, sourceImageId: 'keep-frame.jpg' })
    const run = setup(t, drafts, { fetch: async () => {
      if (failure === 'offline') throw new Error('Offline fixture')
      return { ok: false, status: 503 }
    } })
    await run.ui.restoreVideoSourceImage()
    await nextTick()
    assert.equal(run.state.videoSourceImage.value.id, 'keep-frame.jpg')
    assert.equal(drafts.read(videoKey).sourceImageId, 'keep-frame.jpg')
  })
}

test('late source lookup cannot clear an image selected while the request was pending', async t => {
  let finish
  const run = setup(t, storage({}, { modelId: quality, sourceImageId: 'old-frame.jpg' }), {
    fetch: () => new Promise(resolve => { finish = resolve }),
  })
  const pending = run.ui.restoreVideoSourceImage()
  run.state.videoSourceImage.value = { id: 'new-frame.jpg' }
  finish({ ok: false, status: 404 })
  await pending
  await nextTick()
  assert.equal(run.state.videoSourceImage.value.id, 'new-frame.jpg')
  assert.equal(run.localStorage.read(videoKey).sourceImageId, 'new-frame.jpg')
})

test('Wan clears incompatible source images on reopen and when selected explicitly', async t => {
  const reopened = setup(t, storage({}, { modelId: wan, sourceImageId: 'incompatible-frame.jpg' }))
  assert.equal(reopened.state.videoSourceImage.value, null)
  await reopened.ui.restoreVideoSourceImage()
  assert.equal(reopened.requests.length, 0)
  const drafts = storage({}, { modelId: quality, sourceImageId: 'first-frame.jpg' })
  const run = setup(t, drafts)
  run.state.videoModelId.value = wan
  await nextTick()
  assert.equal(run.state.videoSourceImage.value, null)
  assert.equal(drafts.read(videoKey).sourceImageId, null)
})
