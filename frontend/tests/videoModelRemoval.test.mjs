import test from 'node:test'
import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import vm from 'node:vm'

const source = await readFile(new URL('../src/App.vue', import.meta.url), 'utf8')
const ids = source.match(/^const videoModelIds = .*$/m)[0]
const load = source.slice(source.indexOf('function loadVideoGenerationSettings()'), source.indexOf('const savedGenerationSettings'))
test('previously selected removed model falls back with compatible steps and keeps the prompt', () => {
  const context = vm.createContext({
    window: { localStorage: { getItem: () => JSON.stringify({modelId: 'hunyuanvideo-1.5-480p', steps: 30, prompt: 'Keep my prompt'}) } },
    videoGenerationSettingsKey: 'settings', createRandomSeed: () => 7,
  })
  vm.runInContext(ids + '\n' + load + '\nresult = loadVideoGenerationSettings()', context)
  assert.equal(context.result.modelId, 'ltx-2b-0.9.6-distilled')
  assert.equal(context.result.steps, 8)
  assert.equal(context.result.prompt, 'Keep my prompt')
})

const restore = source.slice(source.indexOf('async function useSavedVideoSettings('), source.indexOf('async function saveSavedVideoToDisplaySdCard('))
test('restoring an older video cannot reselect a removed model or invalid step count', async () => {
  const context = { nextTick: async () => { context.videoSteps.value = 8 }, createRandomSeed: () => 7 }
  for (const name of ['savedVideoContextMenu', 'videoPrompt', 'videoDurationPresetSeconds', 'videoFrames', 'videoFps', 'videoModelId', 'videoSteps', 'videoSeed', 'videoSourceImage', 'page', 'videoStage', 'metadataPanePinned', 'metadataPane']) context[name] = { value: null }
  context.savedImages = { value: [] }
  context.videoStepOptions = { value: [4, 5, 6, 7, 8] }
  vm.createContext(context)
  vm.runInContext(ids + '\n' + restore, context)
  await context.useSavedVideoSettings({model: {id: 'hunyuanvideo-1.5-480p'}, steps: 30, prompt: 'Original prompt', seed: 12, frames: 25, fps: 8}, 'all')
  assert.equal(context.videoModelId.value, 'ltx-2b-0.9.6-distilled')
  assert.equal(context.videoSteps.value, 8)
  assert.equal(context.videoPrompt.value, 'Original prompt')
  assert.match(context.videoStage.value, /no longer available/)
})
