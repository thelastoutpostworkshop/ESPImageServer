import test from 'node:test'
import assert from 'node:assert/strict'
import { serialPorts, isSerialPortPath, requireDetectedPort } from './serial-ports.mjs'
import { FirmwareInstaller } from './firmware.mjs'
import { reconnectCandidate } from './identification.mjs'

const paths = ['COM26', '/dev/ttyUSB0', '/dev/ttyACM0', '/dev/cu.usbmodem1101', '/dev/tty.usbserial-001']

test('enumeration preserves cross-platform paths and USB identity, without duplicates', async () => {
  const ports = await serialPorts(async () => [...paths, 'COM26', '/tmp/file', '/dev/tty/../../etc/passwd'].map(path =>
    ({ path, serialNumber: 'device', vendorId: '303a', productId: '1001', manufacturer: 'Maker' })))
  assert.deepEqual(ports.map(p => p.port), paths)
  for (const port of ports) {
    assert.equal(port.serialNumber, 'device')
    assert.equal(port.vendorId, '303a')
    assert.equal(port.productId, '1001')
    assert.ok(port.label.includes(port.port))
  }
})

test('invalid and unenumerated paths cannot be selected', () => {
  for (const name of ['', null, 4, 'COM0', 'COM2\n', '/etc/passwd', '/dev/ttyUSB0\n', '/dev/tty../file', '--port', 'COM4 & cmd']) {
    assert.equal(isSerialPortPath(name), false, String(name))
  }
  assert.throws(() => requireDetectedPort('/dev/ttyUSB0', []), /no longer available/)
})

for (const port of paths) {
  test(`${port}: selection and identification require current enumeration`, async () => {
    let connected = true, calls = 0
    const installer = new FirmwareInstaller('fake', { ports: async () => connected ? [{ port }] : [],
      identify: async selected => { calls++; return { port: selected, hardware_id: 'aabbccddeeff' } } })
    assert.throws(() => installer.selectPort(port), /Refresh ports/)
    await installer.refreshPorts()
    installer.selectPort(port)
    await installer.identifyFirmware(port)
    assert.equal(installer.state.identity.port, port)
    connected = false
    await installer.refreshIdentity(port)
    assert.equal(installer.state.identity, null)
    assert.equal(calls, 1)
    await installer.identifyFirmware(port)
    assert.equal(calls, 1)
    assert.match(installer.state.identityError, /no longer available/)
    installer.selectPort('')
    assert.equal(installer.state.selectedPort, '')
  })
}

test('Linux/macOS renumbering still requires unique USB identity', () => {
  const original = { port: '/dev/ttyACM0', serialNumber: 'one', vendorId: '303a' }
  const moved = { ...original, port: '/dev/ttyACM1' }
  assert.equal(reconnectCandidate(original, [moved]), moved)
  assert.equal(reconnectCandidate(original, [moved, { ...moved, port: '/dev/cu.usbmodem1' }]), null)
  assert.equal(reconnectCandidate(original, [{ ...moved, serialNumber: 'two' }]), null)
})
