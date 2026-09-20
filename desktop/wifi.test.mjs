import test from 'node:test'
import assert from 'node:assert/strict'
import { EventEmitter } from 'node:events'
import { WifiSetup, WifiSerialSession, validateCredentials, validateWifi } from './wifi.mjs'
import { responseDecoder } from './identification.mjs'

const identity = { hardware_id: 'aabbccddeeff', board_target: 'JC4827W543', board_name: 'Display',
  firmware_version: '1.1.3', protocol_version: 1, capabilities: ['hello', 'status', 'wifi_scan', 'wifi_connect', 'wifi_cancel', 'wifi_status'],
  width: 480, height: 272, wifi_configured: false, wifi_connected: false, port: 'COM8' }
const response = result => ({ protocol: 1, ok: true, result })
const status = (stage, extra = {}) => response({ wifi_state: stage, wifi_error: '', wifi_configured: stage === 'connected',
  wifi_connected: stage === 'connected', ip: stage === 'connected' ? '192.168.1.10' : '', networks: [], ...extra })
const request = { action: 'connect', port: 'COM8', hardwareId: identity.hardware_id, ssid: 'Test network', password: 'test-password', auth: 'personal' }
const installer = () => ({ ports: async () => [{ port: 'COM8' }], state: { busy: false, identity: { ...identity } }, snapshot() { return structuredClone(this.state) } })
function fakeSession(overrides = {}) {
  return { commands: [], async open() {}, async close() { this.closed = true },
    async request(command, payload) {
      this.commands.push({ command, payload: structuredClone(payload) })
      if (command === 'hello') return response(identity)
      if (command === 'wifi_cancel') return status('cancelled')
      if (command === 'wifi_connect') return status('connecting')
      return status('connected')
    }, ...overrides }
}

for (const port of ['/dev/ttyUSB0', '/dev/ttyACM0', '/dev/cu.usbmodem1101']) {
  test(`${port}: Wi-Fi setup preserves hardware binding and checks enumeration`, async () => {
    const inst = installer(), session = fakeSession()
    inst.state.identity.port = port
    inst.ports = async () => [{ port }]
    const setup = new WifiSetup(inst, { session: selected => { assert.equal(selected, port); return session }, pause: async () => {} })
    setup.start({ ...request, port })
    await setup.completion
    assert.equal(inst.state.wifi.stage, 'connected')
    assert.equal(session.commands.find(c => c.command === 'wifi_connect').payload.hardware_id, identity.hardware_id)
    inst.ports = async () => []
    setup.session = () => { assert.fail('Disconnected port must not be opened') }
    setup.start({ ...request, port })
    await setup.completion
    assert.equal(inst.state.wifi.stage, 'failed')
    assert.match(inst.state.wifi.error, /no longer available/)
  })
}

test('credentials validate UTF-8 SSID lengths, open networks, ASCII passphrases and raw keys', () => {
  assert.equal(validateCredentials(request).ssid, request.ssid)
  assert.doesNotThrow(() => validateCredentials({ ssid: 'Hidden', password: '', auth: 'open' }))
  assert.doesNotThrow(() => validateCredentials({ ...request, password: 'a'.repeat(64) }))
  for (const change of [{ ssid: 'é'.repeat(17) }, { ssid: 'a\0b' }, { password: 'short' },
    { password: 'x'.repeat(64) }, { password: 'é'.repeat(8) }, { auth: 'enterprise' }, { auth: 'open' }]) {
    assert.throws(() => validateCredentials({ ...request, ...change }), /SSID/)
  }
})
test('responses whitelist fields and never display arbitrary firmware errors', () => {
  const clean = validateWifi(status('connected', { password: 'test-secret', networks: [{ ssid: 'Network', auth: 'open', rssi: -50, password: 'secret' }] }))
  assert.ok(!JSON.stringify(clean).includes('secret'))
  assert.throws(() => validateWifi({ protocol: 1, ok: false, error: 'test-secret' }), error => !error.message.includes('secret'))
  assert.throws(() => validateWifi(status('connected', { networks: Array(21).fill({}) })), /Invalid/)
  assert.throws(() => validateWifi(status('unknown')), /Invalid/)
  assert.throws(() => validateWifi(status('connected', { ip: '999.1.2.3' })), /Invalid/)
  assert.throws(() => validateWifi(status('connected', { wifi_configured: false })), /did not confirm/)
  assert.throws(() => validateWifi(status('connected', { ip: '0.0.0.0' })), /did not confirm/)
})
test('decoder preserves Unicode networks split across UTF-8 bytes and drops oversized lines', () => {
  const results = [], decode = responseDecoder(null, r => results.push(r), 16384)
  decode(Buffer.from('x'.repeat(17000) + '\n'))
  const bytes = Buffer.from('@ESPIMAGE ' + JSON.stringify({ id: 'a', ssid: 'Café 日本' }) + '\n')
  for (const byte of bytes) decode(Buffer.from([byte]))
  assert.deepEqual(results, [{ id: 'a', ssid: 'Café 日本' }])
})
test('connect keeps one session and shared flash lock, binds hardware ID, and strips credentials', async () => {
  const inst = installer(), session = fakeSession()
  const setup = new WifiSetup(inst, { session: () => session, pause: async () => {} })
  assert.equal(setup.start(request).busy, true)
  assert.throws(() => setup.start(request), /current USB/)
  assert.ok(!JSON.stringify(inst.snapshot()).includes(request.password))
  await setup.completion
  assert.equal(inst.state.wifi.stage, 'connected'); assert.equal(inst.state.identity.wifi_configured, true)
  assert.equal(inst.state.busy, false); assert.ok(session.closed)
  assert.equal(session.commands.find(c => c.command === 'wifi_connect').payload.hardware_id, identity.hardware_id)
  assert.ok(!JSON.stringify(inst.snapshot()).includes(request.password))
})
test('different hardware on the same COM port never receives credentials', async () => {
  const inst = installer(), session = fakeSession({ async request(command) {
    assert.equal(command, 'hello'); return response({ ...identity, hardware_id: '000000000000' })
  } })
  const setup = new WifiSetup(inst, { session: () => session })
  setup.start(request); await setup.completion
  assert.equal(inst.state.wifi.stage, 'failed'); assert.match(inst.state.wifi.error, /device changed/)
  assert.ok(session.closed); assert.equal(inst.state.busy, false)
})
test('older firmware cannot receive credentials', async () => {
  const inst = installer(), session = fakeSession({ async request(command) {
    assert.equal(command, 'hello'); return response({ ...identity, capabilities: ['hello', 'status'] })
  } })
  const setup = new WifiSetup(inst, { session: () => session })
  setup.start(request); await setup.completion
  assert.match(inst.state.wifi.error, /support/); assert.ok(session.closed)
})
test('cancel during connection is sent on the existing session and releases the lock', async () => {
  const inst = installer(), session = fakeSession()
  const setup = new WifiSetup(inst, { session: () => session, pause: async () => { setup.cancel() } })
  setup.start(request); await setup.completion
  assert.equal(inst.state.wifi.stage, 'cancelled')
  assert.ok(session.commands.some(c => c.command === 'wifi_cancel')); assert.ok(session.closed); assert.equal(inst.state.busy, false)
})
test('disconnect during operation attempts cancellation and closes the session', async () => {
  const inst = installer(), session = fakeSession({ async request(command) {
    if (command === 'hello') return response(identity)
    throw new Error('USB disconnected')
  } })
  const setup = new WifiSetup(inst, { session: () => session })
  setup.start(request); await setup.completion
  assert.equal(inst.state.wifi.stage, 'failed'); assert.ok(session.closed); assert.equal(inst.state.busy, false)
})
test('firmware storage failure is surfaced without marking credentials as saved', async () => {
  const inst = installer(), session = fakeSession({ async request(command) {
    return command === 'hello' ? response(identity) : status('failed', { wifi_error: 'storage_failed' })
  } })
  const setup = new WifiSetup(inst, { session: () => session })
  setup.start(request); await setup.completion
  assert.match(inst.state.wifi.error, /could not save/); assert.equal(inst.state.identity.wifi_configured, false)
})
test('scan returns bounded networks and releases port for the next operation', async () => {
  const inst = installer(), session = fakeSession({ async request(command) {
    return command === 'hello' ? response(identity) : status('scan_complete', { networks: [{ ssid: 'Café', rssi: -40, auth: 'personal' }] })
  } })
  const setup = new WifiSetup(inst, { session: () => session })
  setup.start({ ...request, action: 'scan' }); await setup.completion
  assert.equal(inst.state.wifi.networks[0].ssid, 'Café'); assert.ok(session.closed)
})
class FakePort extends EventEmitter {
  open(callback) { this.isOpen = true; callback() }
  close(callback) { this.isOpen = false; this.emit('close'); callback() }
  write(line, callback) { this.written = JSON.parse(line); callback() }
}
test('serial request timeout does not leak password and close releases the port', async () => {
  const port = new FakePort(), session = new WifiSerialSession('COM8', { createPort: () => port, timeout: 5 })
  await session.open()
  await assert.rejects(session.request('wifi_connect', { password: 'test-secret' }), /timed out/)
  assert.equal(session.pending.size, 0)
  await session.close(); assert.equal(port.isOpen, false)
})
test('serial driver errors are sanitized and reject pending requests', async () => {
  const port = new FakePort(), session = new WifiSerialSession('COM8', { createPort: () => port })
  await session.open()
  const pending = session.request('hello')
  port.emit('error', new Error('test-secret'))
  await assert.rejects(pending, error => !error.message.includes('test-secret'))
  await session.close(); assert.equal(port.isOpen, false)
})

test('hello retries tolerate a board booting after port open, without resending mutations', async () => {
  const port = new FakePort(); let attempts = 0
  port.write = (line, callback) => {
    attempts++; callback()
    if (attempts > 1) port.emit('data', Buffer.from('@ESPIMAGE ' + JSON.stringify({ ...response(identity), id: JSON.parse(line).id }) + '\n'))
  }
  const session = new WifiSerialSession('COM8', { createPort: () => port, timeout: 1500 })
  await session.open()
  assert.equal((await session.request('hello')).result.hardware_id, identity.hardware_id)
  assert.equal(attempts, 2); assert.equal(session.pending.size, 0)
  await session.close()
})
test('a delayed port open retains ownership until cleanup, even after its deadline', async () => {
  const port = new FakePort()
  port.open = callback => setTimeout(() => { port.isOpen = true; callback() }, 20)
  const session = new WifiSerialSession('COM8', { createPort: () => port, timeout: 5 })
  await assert.rejects(session.open(), /Cannot open/)
  await session.close(); assert.equal(port.isOpen, false)
})

test('Forget Wi-Fi requires explicit confirmation before opening any port', () => {
  const setup = new WifiSetup(installer(), { session: () => { throw new Error('must not open') } })
  assert.throws(() => setup.start({ ...request, action: 'forget' }), /Confirm Forget/)
})
test('Forget Wi-Fi checks the live capability before sending the command', async () => {
  const inst = installer(), session = fakeSession()
  const setup = new WifiSetup(inst, { session: () => session })
  setup.start({ ...request, action: 'forget', confirm: true }); await setup.completion
  assert.match(inst.state.wifi.error, /1.1.4/)
  assert.deepEqual(session.commands.map(c => c.command), ['hello'])
  assert.ok(session.closed)
})
test('confirmed Forget Wi-Fi binds the device, omits credentials and verifies removal', async () => {
  const inst = installer(), commands = []
  const session = fakeSession({ async request(command, payload) {
    commands.push({ command, payload })
    if (command === 'hello') return response({ ...identity, firmware_version: '1.1.4', capabilities: [...identity.capabilities, 'wifi_forget'] })
    return status('forgotten')
  } })
  const setup = new WifiSetup(inst, { session: () => session })
  setup.start({ ...request, action: 'forget', confirm: true }); await setup.completion
  assert.equal(inst.state.wifi.stage, 'forgotten')
  assert.equal(inst.state.identity.wifi_configured, false)
  assert.deepEqual(commands[1], { command: 'wifi_forget', payload: { hardware_id: identity.hardware_id, confirm: true } })
  assert.equal(inst.state.busy, false); assert.ok(session.closed)
  assert.throws(() => validateWifi(status('forgotten', { wifi_configured: true })), /did not confirm/)
})
