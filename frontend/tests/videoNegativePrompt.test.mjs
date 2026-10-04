import test from 'node:test'
import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import vm from 'node:vm'
import { ref, computed, watch, nextTick } from 'vue'

const source = await readFile(new URL('../src/App.vue', import.meta.url), 'utf8')
function slice(start, end) {
  const from = source.indexOf(start), to = source.indexOf(end)
  assert.ok(from >= 0 && to > from, `Missing function boundary: ${start} / ${end}`)
  return source.slice(from, to)
}
const ids = source.match(/^const videoModelIds = .*$/m)[0]
const load = slice('function loadVideoGenerationSettings()', 'const savedGenerationSettings')
const initialState = slice('const videoSourceImage =', 'const previewUrl =')
const capabilities = slice('const selectedVideoModelCapabilities =', 'const rotationOptions =')
const watchers = slice('watch([videoPrompt,', 'watch(videoFps,')
const restore = slice('async function useSavedVideoSettings(', 'async function saveSavedVideoToDisplaySdCard(')
const generate = slice('async function generateVideo()', 'async function saveVideoToCreationLibrary()')
const loadCatalog = slice('async function loadVideoModels()', 'function confirmRemoveImageModel(')
const distilled = 'ltx-2b-0.9.6-distilled'
const quality = 'ltx-2b-0.9.6-dev'
const wan = 'wan-2.1-t2v-1.3b'
const catalog = [
  { id: distilled, supports_negative_prompt: false, default_negative_prompt: null },
  { id: quality, supports_negative_prompt: true, default_negative_prompt: 'Quality server default' },
  { id: wan, supports_negative_prompt: true, default_negative_prompt: 'Wan server default' },
]

function storage(settings) {
  let stored = JSON.stringify(settings)
  return { getItem: () => stored, setItem: (_key, value) => { stored = value } }
}

// Use Vue's real refs, computed values, and watcher scheduling. Network replies
// are fixtures: the production request builder never reaches a server or GPU.
function setup(t, localStorage = storage({ modelId: wan })) {
  const disposers = [], requests = []
  const ui = vm.createContext({
    ref, computed, nextTick,
    watch: (...args) => { const stop = watch(...args); disposers.push(stop); return stop },
    window: { localStorage, setTimeout: callback => callback() },
    videoGenerationSettingsKey: 'video-settings', createRandomSeed: () => 42,
    availableVideoModels: ref(catalog),
    savedVideoContextMenu: ref(false), savedImages: ref([]), page: ref('video'),
    metadataPanePinned: ref(false), metadataPane: ref(false),
    savingVideoRotation: ref(false), hasDisplayTargets: ref(false), selectedTargetDisplayIds: ref([]),
    showQueueAddedFeedback: () => {}, loadGenerationQueue: async () => {}, updateGenerationQueueJob: () => {},
    fetch: async (url, options) => {
      assert.equal(url, '/video-generation-jobs')
      assert.equal(options.method, 'POST')
      requests.push(JSON.parse(options.body))
      return { ok: true, json: async () => ({ id: 'fixture-job', status: 'running' }) }
    },
    fetchGenerationResponse: async url => {
      assert.equal(url, '/video-generation-jobs/fixture-job')
      return { ok: true, json: async () => ({ id: 'fixture-job', status: 'cancelled' }) }
    },
  })
  vm.runInContext([
    ids, load, 'const savedVideoGenerationSettings = loadVideoGenerationSettings()',
    initialState, capabilities, watchers, restore, generate, loadCatalog,
    'state = { videoPrompt, videoNegativePrompt, videoNegativePromptValue, videoModelId, videoFrames, videoSeed, randomizeVideoSeed, videoSupportsNegativePrompt, generatingVideo, videoError, videoStage, videoProgress }',
  ].join('\n'), ui)
  t.after(() => disposers.forEach(stop => stop()))
  return { ui, state: ui.state, requests, localStorage }
}

for (const draft of ['blurry, flickering, unwanted text', '', null]) {
  test(`video negative prompt draft ${JSON.stringify(draft)} survives persistence and reload`, async t => {
    const first = setup(t, storage({ modelId: wan, negativePrompt: draft }))
    assert.equal(first.state.videoNegativePrompt.value, draft)
    first.state.videoFrames.value = 33
    await nextTick()
    assert.equal(JSON.parse(first.localStorage.getItem()).negativePrompt, draft)
    const reloaded = setup(t, first.localStorage)
    assert.equal(reloaded.state.videoNegativePrompt.value, draft)
    assert.equal(reloaded.state.videoNegativePromptValue.value, draft ?? 'Wan server default')
    await reloaded.ui.generateVideo()
    assert.equal(reloaded.requests[0].negative_prompt, draft ?? 'Wan server default')
  })
}

test('editing and clearing the field updates storage without reverting to the server default', async t => {
  const run = setup(t)
  assert.equal(run.state.videoNegativePromptValue.value, 'Wan server default')
  run.state.videoNegativePromptValue.value = 'avoid text'
  await nextTick()
  assert.equal(JSON.parse(run.localStorage.getItem()).negativePrompt, 'avoid text')
  run.state.videoNegativePromptValue.value = ''
  await nextTick()
  const reloaded = setup(t, run.localStorage)
  assert.equal(reloaded.state.videoNegativePromptValue.value, '')
  await reloaded.ui.generateVideo()
  assert.equal(reloaded.requests[0].negative_prompt, '')
})

test('legacy or invalid local drafts safely select the current server default', async t => {
  for (const settings of [{ modelId: wan }, { modelId: wan, negativePrompt: 123 }]) {
    const run = setup(t, storage(settings))
    assert.equal(run.state.videoNegativePrompt.value, null)
    assert.equal(run.state.videoNegativePromptValue.value, 'Wan server default')
  }
  const broken = setup(t, { getItem: () => '{invalid', setItem: () => {} })
  assert.equal(broken.state.videoNegativePrompt.value, null)
  assert.equal(broken.state.videoModelId.value, distilled)
})

test('server capability loading supplies defaults without making them a stored draft', async t => {
  const run = setup(t)
  run.ui.availableVideoModels.value = []
  assert.equal(run.state.videoSupportsNegativePrompt.value, false)
  assert.equal(run.state.videoNegativePromptValue.value, '')
  run.ui.availableVideoModels.value = catalog
  assert.equal(run.state.videoSupportsNegativePrompt.value, true)
  assert.equal(run.state.videoNegativePromptValue.value, 'Wan server default')
  run.state.videoModelId.value = quality
  await nextTick()
  assert.equal(run.state.videoNegativePromptValue.value, 'Quality server default')
  assert.equal(JSON.parse(run.localStorage.getItem()).negativePrompt, null)
})

test('unknown selected-model capabilities block submission without losing a draft or changing queue state', async t => {
  const run = setup(t, storage({ modelId: wan, negativePrompt: 'keep exclusions', seed: 7, randomizeSeed: true }))
  let queueUpdates = 0
  run.ui.showQueueAddedFeedback = () => { ++queueUpdates }
  run.ui.loadGenerationQueue = async () => { ++queueUpdates }
  run.ui.availableVideoModels.value = [catalog[0]]
  run.state.videoStage.value = 'Previous stage'
  run.state.videoProgress.value = 20
  await run.ui.generateVideo()
  assert.match(run.state.videoError.value, /model settings are not available/)
  assert.equal(run.state.generatingVideo.value, false)
  assert.equal(run.state.videoStage.value, 'Previous stage')
  assert.equal(run.state.videoProgress.value, 20)
  assert.equal(run.state.videoSeed.value, 7)
  assert.equal(run.state.videoNegativePrompt.value, 'keep exclusions')
  assert.equal(run.requests.length, 0)
  assert.equal(queueUpdates, 0)
  run.ui.availableVideoModels.value = catalog
  await run.ui.generateVideo()
  assert.equal(run.requests[0].negative_prompt, 'keep exclusions')
})

for (const failure of ['non-OK response', 'fetch rejection', 'invalid JSON']) {
  test(`catalog ${failure} preserves known negative-prompt capabilities and defaults`, async t => {
    const run = setup(t), knownCatalog = run.ui.availableVideoModels.value
    const submit = run.ui.fetch
    run.ui.fetch = async (url, options) => {
      if (url !== '/video-models') return submit(url, options)
      if (failure === 'fetch rejection') throw new Error('Temporary connection failure')
      if (failure === 'non-OK response') return { ok: false, status: 503 }
      return { ok: true, json: async () => { throw new SyntaxError('Invalid fixture JSON') } }
    }
    await run.ui.loadVideoModels()
    assert.equal(run.ui.availableVideoModels.value, knownCatalog)
    assert.equal(run.state.videoSupportsNegativePrompt.value, true)
    assert.equal(run.state.videoNegativePromptValue.value, 'Wan server default')
    assert.equal(run.state.videoNegativePrompt.value, null)
    await run.ui.generateVideo()
    assert.equal(run.requests[0].negative_prompt, 'Wan server default')
  })
}

for (const setting of ['prompt', 'all']) {
  for (const [label, metadata, expectedDraft] of [
    ['saved text', { negative_prompt: 'saved exclusions' }, 'saved exclusions'],
    ['saved blank', { negative_prompt: '' }, ''],
    ['explicit no prompt', { negative_prompt: null }, ''],
    ['legacy missing prompt', {}, null],
  ]) {
    test(`restoring ${setting} handles ${label} and persists the result`, async t => {
      const run = setup(t, storage({ modelId: wan, negativePrompt: 'previous draft' }))
      await run.ui.useSavedVideoSettings({ prompt: 'Restored scene', model: { id: wan }, ...metadata }, setting)
      await nextTick()
      assert.equal(run.state.videoPrompt.value, 'Restored scene')
      assert.equal(run.state.videoNegativePrompt.value, expectedDraft)
      const reloaded = setup(t, run.localStorage)
      assert.equal(reloaded.state.videoNegativePrompt.value, expectedDraft)
      await reloaded.ui.generateVideo()
      assert.equal(reloaded.requests[0].negative_prompt, expectedDraft ?? 'Wan server default')
    })
  }
}

test('restoring a seed alone preserves the negative prompt draft', async t => {
  const run = setup(t, storage({ modelId: wan, negativePrompt: 'keep exclusions' }))
  await run.ui.useSavedVideoSettings({ seed: 7, negative_prompt: 'unrelated saved prompt' }, 'seed')
  assert.equal(run.state.videoSeed.value, 7)
  assert.equal(run.state.videoNegativePrompt.value, 'keep exclusions')
})

test('distilled hides and excludes a retained draft while supported models reuse it after switching', async t => {
  const run = setup(t, storage({ modelId: quality, negativePrompt: 'retain this draft' }))
  await run.ui.generateVideo()
  run.state.videoModelId.value = distilled
  await nextTick()
  assert.equal(run.state.videoSupportsNegativePrompt.value, false)
  assert.equal(run.state.videoNegativePrompt.value, 'retain this draft')
  await run.ui.generateVideo()
  run.state.videoModelId.value = wan
  await nextTick()
  assert.equal(run.state.videoSupportsNegativePrompt.value, true)
  await run.ui.generateVideo()
  run.state.videoModelId.value = quality
  await nextTick()
  await run.ui.generateVideo()
  assert.deepEqual(run.requests.map(request => [request.model_id, request.negative_prompt]), [
    [quality, 'retain this draft'], [distilled, null], [wan, 'retain this draft'], [quality, 'retain this draft'],
  ])
  assert.equal(JSON.parse(run.localStorage.getItem()).negativePrompt, 'retain this draft')
  assert.equal(run.state.generatingVideo.value, false)
})
