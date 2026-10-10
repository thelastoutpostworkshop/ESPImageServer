import test from 'node:test'
import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import { compileScript, parse } from '@vue/compiler-sfc'
import { createRenderer, h, nextTick, reactive } from 'vue'
import { matchSetupDisplay } from '../src/setupConnection.js'

const identity = { hardware_id: 'aabbccddeeff', firmware_version: '1.1.3', width: 480, height: 272, port: 'COM8', wifi_connected: true }
const now = Date.now()
const display = { ...identity, id: identity.hardware_id, name: 'My display', online: true, last_seen: new Date(now).toISOString() }
test('Ready requires the exact USB identity and the server to report it online', () => {
  assert.equal(matchSetupDisplay(identity, [display]), display)
  for (const change of [{ hardware_id: '112233445566' }, { firmware_version: '1.1.2' }, { width: 320 }, { height: 480 },
    { online: false }, { online: undefined }]) {
    assert.equal(matchSetupDisplay(identity, [{ ...display, ...change }]), null)
  }
  assert.equal(matchSetupDisplay(identity, [display, display]), null)
  assert.equal(matchSetupDisplay({ ...identity, wifi_connected: false }, [display]), null)
  assert.equal(matchSetupDisplay({}, [{}]), null)
})

const filename = new URL('../src/components/SetupConnection.vue', import.meta.url)
const { descriptor } = parse(await readFile(filename, 'utf8'))
const script = compileScript(descriptor, { id: 'setup-connection-test' }).content
  .replace(/from ['"]vue['"]/g, `from ${JSON.stringify(import.meta.resolve('vue'))}`)
  .replace("from '../setupConnection.js'", `from ${JSON.stringify(new URL('../src/setupConnection.js', import.meta.url).href)}`)
const { default: component } = await import(`data:text/javascript;base64,${Buffer.from(script).toString('base64')}`)
component.render = () => null
const renderer = createRenderer({ createComment: () => ({}), insert() {}, remove() {}, parentNode: () => null,
  nextSibling: () => null, createElement: () => ({}), createText: () => ({}), setText() {}, setElementText() {}, patchProp() {} })
const flush = async () => { await nextTick(); await new Promise(resolve => setImmediate(resolve)) }
function mount(t, fetcher, changes = {}) {
  const originalFetch = globalThis.fetch
  globalThis.fetch = fetcher
  const props = reactive({ identity: { ...identity }, selectedPort: 'COM8', locked: false, ...changes })
  const events = []
  const generations = []
  const app = renderer.createApp({ render: () => h(component, {
    ...props, onReady: ready => events.push(ready), onGenerate: request => generations.push(request)
  }) })
  app.mount({})
  t.after(() => { app.unmount(); globalThis.fetch = originalFetch })
  return { props, input: app._instance.subTree.component.props, state: app._instance.subTree.component.setupState, events, generations }
}

test('an already-online display is Ready immediately and stays Ready between announcements', async t => {
  // Firmware announcements can be a minute apart; opening setup must not
  // impose a shorter timeout or require a new announcement after it opens.
  const alreadyOnline = { ...display, last_seen: new Date(Date.now() - 60000).toISOString() }
  let online = true
  const view = mount(t, async () => ({ ok: true, json: async () => [{ ...alreadyOnline, online }] }))
  await flush()
  assert.equal(view.state.found.id, display.id)
  assert.equal(view.events.at(-1), true)
  view.state.restart(); await flush()
  assert.equal(view.state.found.id, display.id)
  online = false
  view.state.restart(); await flush()
  assert.equal(view.state.found, null)
  assert.equal(view.events.at(-1), false)
})
test('late LAN replies cannot mark a newly selected USB board ready', async t => {
  const requests = []
  const view = mount(t, () => new Promise(resolve => requests.push(resolve)))
  view.props.identity = { ...identity, hardware_id: '112233445566' }
  await flush()
  assert.equal(requests.length, 2)
  requests[0]({ ok: true, json: async () => [{ ...display, last_seen: new Date().toISOString() }] })
  await flush()
  assert.equal(view.state.found, null)
  assert.ok(!view.events.includes(true))
  requests[1]({ ok: true, json: async () => [{ ...display, hardware_id: '112233445566', last_seen: new Date().toISOString() }] })
  await flush()
  assert.equal(view.state.found.hardware_id, '112233445566')
})
test('server outage retains USB Wi-Fi state and can recover without credentials', async t => {
  let available = false
  const view = mount(t, async () => {
    if (!available) throw new Error('offline')
    return { ok: true, json: async () => [{ ...display, last_seen: new Date().toISOString() }] }
  })
  await flush()
  assert.equal(view.state.serverError, true)
  assert.equal(view.props.identity.wifi_connected, true)
  available = true; view.state.restart(); await flush()
  assert.equal(view.state.serverError, false)
  assert.equal(view.state.found.hardware_id, identity.hardware_id)
})
test('port changes or USB work immediately withdraw Ready', async t => {
  const view = mount(t, async () => ({ ok: true, json: async () => [{ ...display, last_seen: new Date().toISOString() }] }))
  await flush(); assert.ok(view.state.found)
  view.props.locked = true; await flush(); assert.equal(view.state.found, null)
  view.props.selectedPort = 'COM9'; view.props.locked = false; await flush()
  assert.equal(view.state.eligible, false); assert.equal(view.state.found, null)
})

test('Ready image and video actions identify the matched display and selected generation kind', async t => {
  const view = mount(t, async () => ({ ok: true, json: async () => [display] }))
  await flush()
  assert.equal(view.state.found.id, display.id)
  view.state.generate('image')
  view.state.generate('video')
  assert.deepEqual(view.generations, [
    { displayId: display.id, kind: 'image' },
    { displayId: display.id, kind: 'video' }
  ])
})

test('generation actions do not open a destination before the exact display is matched', async t => {
  const view = mount(t, async () => ({ ok: true, json: async () => [{ ...display, hardware_id: '112233445566' }] }))
  await flush()
  assert.equal(view.state.eligible, true)
  assert.equal(view.state.found, null)
  view.state.generate('image')
  view.state.generate('video')
  assert.deepEqual(view.generations, [])
})

test('generation actions stop immediately when USB setup is locked or identity becomes ineligible', async t => {
  for (const [name, change] of [
    ['USB work starts', props => { props.locked = true }],
    ['another port is selected', props => { props.selectedPort = 'COM9' }],
    ['Wi-Fi disconnects', props => { props.identity = { ...identity, wifi_connected: false } }],
    ['USB identity is lost', props => { props.identity = null }]
  ]) {
    await t.test(name, async t => {
      const view = mount(t, async () => ({ ok: true, json: async () => [display] }))
      await flush()
      assert.ok(view.state.found)
      change(view.input)
      // Exercise a click before the queued watcher removes the old match.
      // Eligibility must protect against a stale Ready screen in that interval.
      view.state.generate('image')
      view.state.generate('video')
      assert.deepEqual(view.generations, [])
      assert.equal(view.state.eligible, false)
    })
  }
})

test('Ready ignores unsupported generation destinations', async t => {
  const view = mount(t, async () => ({ ok: true, json: async () => [display] }))
  await flush()
  assert.ok(view.state.found)
  for (const kind of ['display', '', 'Image', 'video ', null, undefined]) view.state.generate(kind)
  assert.deepEqual(view.generations, [])
})

const appSource = await readFile(new URL('../src/App.vue', import.meta.url), 'utf8')
const setupGenerationHandler = appSource.match(/^function openSetupGeneration\([\s\S]+?^\}/m)?.[0]
function generationDestination() {
  assert.ok(setupGenerationHandler, 'App handles the Ready generation action')
  const calls = []
  const handle = new Function('selectActiveDisplay', 'openGeneratePage', 'navigate',
    `${setupGenerationHandler}\nreturn openSetupGeneration`)(
    id => calls.push(['selectDisplay', id]),
    () => calls.push(['openImageGeneration']),
    page => calls.push(['navigate', page])
  )
  return { handle, calls }
}

test('the Ready image handoff selects its confirmed board before opening image generation', () => {
  const {handle,calls} = generationDestination()
  handle({displayId:display.id,kind:'image'})
  assert.deepEqual(calls, [['selectDisplay',display.id],['openImageGeneration']])
})

test('the Ready video handoff selects its confirmed board before opening video generation', () => {
  const {handle,calls} = generationDestination()
  handle({displayId:display.id,kind:'video'})
  assert.deepEqual(calls, [['selectDisplay',display.id],['navigate','video']])
})

test('the Ready handoff rejects missing boards and unsupported destinations', () => {
  const {handle,calls} = generationDestination()
  for (const request of [{displayId:'',kind:'image'}, {kind:'video'}, {displayId:display.id,kind:'display'}]) handle(request)
  assert.deepEqual(calls, [])
})
