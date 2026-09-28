import test from 'node:test'
import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import { compileScript, parse } from '@vue/compiler-sfc'
import { createRenderer, h, nextTick, reactive } from 'vue'

const { descriptor } = parse(await readFile(new URL('../src/components/FirmwareUpdateNotice.vue', import.meta.url), 'utf8'))
const script = compileScript(descriptor, { id: 'firmware-updates-test' }).content
  .replace(/from ['"]vue['"]/g, `from ${JSON.stringify(import.meta.resolve('vue'))}`)
const { default: component } = await import(`data:text/javascript;base64,${Buffer.from(script).toString('base64')}`)
component.render = () => null
const renderer = createRenderer({ createComment: () => ({}), insert() {}, remove() {}, parentNode: () => null,
  nextSibling: () => null, createElement: () => ({}), createText: () => ({}), setText() {}, setElementText() {}, patchProp() {} })
const flush = async () => { await nextTick(); await new Promise(resolve => setImmediate(resolve)) }
const board = { id: 'one', online: true, firmware_version: '1.1.9' }
const update = { display_id: 'one', installed_version: '1.1.9', version: '1.1.38' }
function mount(t, fetcher, enabled = true) {
  const oldFetch = globalThis.fetch, oldWindow = globalThis.window
  globalThis.fetch = fetcher
  globalThis.window = { setInterval: () => 1, clearInterval() {} }
  const props = reactive({ displays: [{ ...board }], enabled })
  const app = renderer.createApp({ render: () => h(component, props) })
  app.mount({})
  t.after(() => { app.unmount(); globalThis.fetch = oldFetch; globalThis.window = oldWindow })
  return { props, state: app._instance.subTree.component.setupState }
}

test('disabled checks make no request; unchanged polling does not repeat checks', async t => {
  let requests = 0
  const view = mount(t, async () => { requests++; return { ok: true, json: async () => ({ enabled: true, updates: [update] }) } }, false)
  await flush(); assert.equal(requests, 0)
  view.props.enabled = true
  await flush(); assert.equal(view.state.visible.length, 1)
  view.props.displays = [{ ...board }]
  await flush(); assert.equal(requests, 1)
  view.state.dismissed.add('one:1.1.38')
  await view.state.check(); await flush()
  assert.equal(view.state.visible.length, 0)
})

test('offline boards and successfully updated boards lose their notification', async t => {
  const view = mount(t, async () => ({ ok: true, json: async () => ({ enabled: true, updates: [update] }) }))
  await flush(); assert.equal(view.state.visible.length, 1)
  view.props.displays[0].online = false
  await flush(); assert.equal(view.state.visible.length, 0)
  view.props.displays = [{ ...board, firmware_version: '1.1.38' }]
  await flush(); assert.equal(view.state.visible.length, 0)
})

test('a reply arriving after automatic checking is disabled cannot restore a notice', async t => {
  let respond
  const view = mount(t, () => new Promise(resolve => { respond = resolve }))
  view.props.enabled = false
  await flush()
  respond({ ok: true, json: async () => ({ enabled: true, updates: [update] }) })
  await flush()
  assert.equal(view.state.visible.length, 0)
  assert.equal(view.state.updates.length, 0)
})
