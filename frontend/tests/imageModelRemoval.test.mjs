import test from 'node:test'
import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import vm from 'node:vm'
const source = await readFile(new URL('../src/App.vue', import.meta.url), 'utf8')
test('removed image model uses a supported model and its recommended steps', async () => {
  const remaining = [{ id: 'Lykon/dreamshaper-8', active: true, default_steps: 25 }]
  const context = vm.createContext({ models: { value: [] }, activeModelId: { value: 'stabilityai/sd-turbo' }, steps: { value: 1 }, fetch: async () => ({ json: async () => remaining }) })
  vm.runInContext(source.slice(source.indexOf('async function loadModels()'), source.indexOf('async function loadVideoModels()')) + source.slice(source.indexOf('function selectModelById('), source.indexOf('function chooseRandomSeed(')), context)
  await context.loadModels()
  assert.equal(context.activeModelId.value, remaining[0].id)
  assert.equal(context.steps.value, 25)
  context.steps.value = 1
  context.selectModelById('stabilityai/sd-turbo')
  assert.equal(context.steps.value, 25)
})
