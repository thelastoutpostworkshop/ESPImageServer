import test from 'node:test'
import assert from 'node:assert/strict'
import { EventEmitter } from 'node:events'
import { responseDecoder, validateIdentity, identifyPort, reconnectCandidate, identifyAfterFlash } from './identification.mjs'

const result = { hardware_id: 'aabbccddeeff', board_target: 'JC4827W543', board_name: 'JC4827W543 display',
  firmware_version: '1.1.2', protocol_version: 1, capabilities: ['hello', 'status'], width: 480, height: 272,
  wifi_configured: false, wifi_connected: false }
const message = id => ({ protocol: 1, id, ok: true, result })

test('early 1.1.3 unprefixed replies retain protocol and request correlation', () => {
  const received = [], decode = responseDecoder('test-113', r => received.push(r))
  decode(JSON.stringify({ id: 'test-113', note: 'ordinary JSON log' }) + '\n')
  decode(JSON.stringify({ ...message('test-113'), protocol: 2 }) + '\n')
  decode(JSON.stringify(message('unrelated')) + '\n')
  decode('boot log ' + JSON.stringify(message('test-113')) + '\n')
  const raw = JSON.stringify(message('test-113')) + '\n'
  decode(raw.slice(0, 31)); decode(raw.slice(31))
  assert.equal(received.length, 1)
  assert.equal(validateIdentity(received[0]).hardware_id, result.hardware_id)
})
test('decoder recovers from boot logs, oversized input, fragmentation and unrelated replies', () => {
  const received = [], decode = responseDecoder('abc', r => received.push(r))
  decode('boot log\n' + 'x'.repeat(9000) + '\n@ESPIMAGE broken json\n')
  decode('@ESPIMAGE ' + JSON.stringify(message('other')) + '\n')
  const line = '@ESPIMAGE ' + JSON.stringify(message('abc')) + '\n'
  for (let i = 0; i < line.length; i += 7) decode(line.slice(i, i + 7))
  assert.equal(received.length, 1)
  assert.equal(validateIdentity(received[0]).hardware_id, result.hardware_id)
})
test('identity validation rejects unsupported versions and strips unknown data', () => {
  assert.throws(() => validateIdentity({ ...message('abc'), protocol: 2 }), /Unsupported/)
  assert.throws(() => validateIdentity({ ...message('abc'), result: { ...result, hardware_id: 'invalid' } }), /Invalid/)
  const clean = validateIdentity({ ...message('abc'), result: { ...result, password: 'test-secret' } })
  assert.ok(!Object.hasOwn(clean, 'password'))
})
class FakePort extends EventEmitter {
  constructor(respond = true) { super(); this.respond = respond; this.closed = false }
  open(callback) { this.isOpen = true; callback() }
  write(line, callback) {
    callback()
    if (this.respond) this.emit('data', Buffer.from('@ESPIMAGE ' + JSON.stringify(message(JSON.parse(line).id)) + '\n'))
  }
  close(callback) { this.isOpen = false; this.closed = true; this.emit('close'); callback() }
}
for (const portName of ['COM8', '/dev/ttyUSB0', '/dev/ttyACM0', '/dev/cu.usbmodem1101']) test(`${portName}: read-only identification closes the port after success without resetting`, async () => {
  const port = new FakePort()
  const identity = await identifyPort(portName, { createPort: options => {
    assert.equal(options.path, portName)
    assert.equal(options.autoOpen, false); assert.equal(options.lock, true); return port
  } })
  assert.equal(identity.firmware_version, '1.1.2'); assert.ok(port.closed)
})
test('timeout releases the serial port and explains recovery', async () => {
  const port = new FakePort(false)
  await assert.rejects(identifyPort('COM8', { timeout: 10, createPort: () => port }), /identify your display/)
  assert.ok(port.closed)
})
test('a disconnected board releases its identification attempt', async () => {
  const port = new FakePort(false)
  const pending = identifyPort('COM8', { createPort: () => port })
  port.isOpen = false; port.emit('close')
  await assert.rejects(pending, /disconnected/)
})
test('timeout during open waits for port cleanup before releasing its caller', async () => {
  const port = new FakePort(false)
  port.open = callback => { setTimeout(() => { port.isOpen = true; callback() }, 30) }
  await assert.rejects(identifyPort('COM8', { timeout: 5, createPort: () => port }), /identify your display/)
  assert.ok(port.closed)
})
test('COM renumbering matches only a unique USB identity, never a different board', () => {
  const original = { port: 'COM8', serialNumber: 'device1', vendorId: '303a', productId: '1001' }
  const moved = { ...original, port: 'COM12' }
  assert.equal(reconnectCandidate(original, [moved]).port, 'COM12')
  assert.equal(reconnectCandidate(original, [{ ...moved, serialNumber: 'device2' }]), null)
  assert.equal(reconnectCandidate(original, [moved, { ...moved, port: 'COM13' }]), null)
})
test('automatic post-flash check validates board, version and prior hardware ID', async () => {
  const original = { port: 'COM8', vendorId: '303a', productId: '1001', serialNumber: 'device1' }
  const options = { ports: async () => [{ ...original, port: 'COM12' }], identify: async () => result, pause: async () => {}, timeout: 1 }
  const identity = await identifyAfterFlash(original, { board: result.board_target, version: result.firmware_version }, options)
  assert.equal(identity.hardware_id, result.hardware_id)
  await assert.rejects(identifyAfterFlash(original, { board: result.board_target, version: '1.1.1' }, options), /does not match/)
  await assert.rejects(identifyAfterFlash(original, { board: result.board_target, version: result.firmware_version, hardwareId: '000000000000' }, options), /does not match/)
})


test('AMOLED identity preserves its board target and square native dimensions', () => {
  const amoled = { ...message('amoled'), result: { ...result, board_target: 'ESP32_S3_AMOLED_143',
    board_name: 'Waveshare 1.43inch AMOLED', width: 466, height: 466 } }
  const identity = validateIdentity(amoled)
  assert.equal(identity.board_target, 'ESP32_S3_AMOLED_143')
  assert.equal(identity.width, 466)
  assert.equal(identity.height, 466)
})
