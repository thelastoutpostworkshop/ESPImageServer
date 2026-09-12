import test from 'node:test'
import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import { compileScript, parse } from '@vue/compiler-sfc'
import { createRenderer, h, nextTick, reactive } from 'vue'
import { matchSetupDisplay } from '../src/setupConnection.js'

const identity = { hardware_id: 'aabbccddeeff', firmware_version: '1.1.3', width: 480, height: 272, port: 'COM8', wifi_connected: true }
const now = Date.now()
const display = { ...identity, id: identity.hardware_id, name: 'My display', online: true, last_seen: new Date(now).toISOString() }
test('Ready requires the exact USB hardware identity and a fresh matching LAN report', () => {
  assert.equal(matchSetupDisplay(identity, [display], now - 1000, now), display)
  for (const change of [{ hardware_id: '112233445566' }, { firmware_version: '1.1.2' }, { width: 320 },
    { online: false }, { last_seen: new Date(now - 30000).toISOString() }, { last_seen: 'invalid' }]) {
    assert.equal(matchSetupDisplay(identity, [{ ...display, ...change }], now - 1000, now), null)
  }
  assert.equal(matchSetupDisplay(identity, [display, display], now - 1000, now), null)
  assert.equal(matchSetupDisplay({ ...identity, wifi_connected: false }, [display], now - 1000, now), null)
  assert.equal(matchSetupDisplay(identity, [display], now + 1000, now), null)
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
  const app = renderer.createApp({ render: () => h(component, { ...props, onReady: ready => events.push(ready) }) })
  app.mount({})
  t.after(() => { app.unmount(); globalThis.fetch = originalFetch })
  return { props, state: app._instance.subTree.component.setupState, events }
}
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
