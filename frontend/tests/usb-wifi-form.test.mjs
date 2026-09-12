import test from 'node:test'
import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import { compileScript, parse } from '@vue/compiler-sfc'
import { createRenderer, h, nextTick, reactive } from 'vue'

// Exercise the real component's setup/watchers without a browser or USB device.
// Rendering is checked separately in the browser; no Vuetify DOM is needed here.
const source = await readFile(new URL('../src/components/UsbWifiSetup.vue', import.meta.url), 'utf8')
const { descriptor } = parse(source)
const script = compileScript(descriptor, { id: 'usb-wifi-form-test' }).content
  .replace(/from ['"]vue['"]/g, `from ${JSON.stringify(import.meta.resolve('vue'))}`)
const { default: component } = await import(`data:text/javascript;base64,${Buffer.from(script).toString('base64')}`)
component.render = () => null
const renderer = createRenderer({
  createComment: () => ({}), insert() {}, remove() {}, parentNode: () => null,
  nextSibling: () => null, createElement: () => ({}), createText: () => ({}),
  setText() {}, setElementText() {}, patchProp() {}
})

function mount(t) {
  globalThis.window = { espImageServerDesktop: { startWifiSetup() {} } }
  const props = reactive({ identity: { hardware_id: 'aabbccddeeff', port: 'COM8', capabilities: ['wifi_connect'] },
    selectedPort: 'COM8', locked: false, state: { hardwareId: 'aabbccddeeff', port: 'COM8', stage: 'scan_complete',
      networks: [{ ssid: 'cgnet', auth: 'personal', rssi: -42 }] } })
  const app = renderer.createApp({ render: () => h(component, props) })
  app.mount({})
  const form = app._instance.subTree.component.setupState
  t.after(() => { app.unmount(); delete globalThis.window })
  form.network = 0
  form.chooseNetwork(0)
  form.password = 'dummy-test-password'
  return { props, form }
}

test('polling unchanged device identity preserves scanned selection and typed credentials', async t => {
  const { props, form } = mount(t)
  assert.equal(form.ssid, 'cgnet')
  for (let i = 0; i < 4; i++) {
    // IPC polling returns fresh objects, even when the device is unchanged.
    props.identity = { ...props.identity, wifi_connected: false }
    props.state = { ...props.state, networks: props.state.networks.map(n => ({ ...n })) }
    await nextTick()
    assert.equal(form.network, 0)
    assert.equal(form.ssid, 'cgnet')
    assert.equal(form.password, 'dummy-test-password')
  }
})

test('changing the hardware ID clears the previous device form', async t => {
  const { props, form } = mount(t)
  props.identity = { ...props.identity, hardware_id: '112233445566' }
  await nextTick()
  assert.equal(form.network, null)
  assert.equal(form.ssid, '')
  assert.equal(form.password, '')
})

test('changing the COM port clears credentials even for the same hardware ID', async t => {
  const { props, form } = mount(t)
  props.selectedPort = 'COM9'
  await nextTick()
  assert.equal(form.network, null)
  assert.equal(form.ssid, '')
  assert.equal(form.password, '')
})
