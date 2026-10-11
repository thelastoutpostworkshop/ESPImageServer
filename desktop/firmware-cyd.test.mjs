import test from 'node:test'
import assert from 'node:assert/strict'
import { mkdtemp, writeFile, readFile, rm, access } from 'node:fs/promises'
import os from 'node:os'
import path from 'node:path'
import { createHash } from 'node:crypto'
import { FirmwareInstaller, parseProbeHardwareId, esptoolFailure } from './firmware.mjs'

const board = 'CHEAP_YELLOW_DISPLAY'
const hardwareId = '988e23f7a608'
const usbPort = { port: 'COM13', serialNumber: 'original-cyd', vendorId: '1a86', productId: '7523' }
const installedIdentity = {
  port: usbPort.port, hardware_id: hardwareId, board_target: board, board_name: 'Cheap Yellow Display',
  firmware_version: '1.1.40', protocol_version: 1, capabilities: ['hello', 'status'], width: 240, height: 320,
  wifi_configured: false, wifi_connected: false,
}
const probe = 'esptool v5.1.0\nConnected to ESP32 on COM13:\nChip type: ESP32-D0WD-V3 (revision v3.1)\nMAC: 08:a6:f7:23:8e:98\nStub flasher running.\nDetected flash size: 4MB\n'
const verified = 'Hash of data verified.\n'.repeat(4) + 'Hard resetting via RTS pin...\n'
const argument = (args, name) => args[args.indexOf(name) + 1]
const sha = data => createHash('sha256').update(data).digest('hex')

// These packages contain only small synthetic buffers. No serial hardware,
// esptool process, firmware build, Wi-Fi credentials, or actual flashing is used.
async function fixture(t, boardTarget = board) {
  const directory = await mkdtemp(path.join(os.tmpdir(), 'espimage-cyd-test-'))
  t.after(() => rm(directory, { recursive: true, force: true }))
  const image = Buffer.alloc(128)
  image[0] = 0xe9
  const chip = boardTarget === board ? 'esp32' : 'esp32s3'
  image.writeUInt16LE(chip === 'esp32' ? 0 : 9, 12)
  const table = Buffer.alloc(96, 255)
  table.writeUInt16LE(0x50aa); table[2] = 0; table[3] = 0
  table.writeUInt32LE(0x10000, 4); table.writeUInt32LE(0x300000, 8)
  const manifest = {
    schema_version: 1, package_type: 'esp-image-display-firmware', installation_type: 'first_install',
    board_target: boardTarget, chip, firmware_version: '1.1.42',
    flash: { mode: 'dio', frequency: '80m', size_bytes: 4194304 }, segments: [],
  }
  for (const [role, file, offset, data] of [
    ['bootloader', 'boot.bin', chip === 'esp32' ? '0x1000' : '0x0', image],
    ['partition_table', 'partitions.bin', '0x8000', table],
    ['ota_data', 'boot_app0.bin', '0xe000', Buffer.alloc(8192)],
    ['application', 'app.bin', '0x10000', image],
  ]) {
    await writeFile(path.join(directory, file), data)
    manifest.segments.push({ role, file, offset, size_bytes: data.length, sha256: sha(data) })
  }
  await writeFile(path.join(directory, 'manifest.json'), JSON.stringify(manifest))
  return { directory, manifest }
}

async function selectedCyd(t, { manual = false, probeOutput = probe, onIdentify, onProbe, onWrite, onReconnect } = {}) {
  const f = await fixture(t)
  const device = { ports: [{ ...usbPort }], identity: { ...installedIdentity } }
  const events = [], calls = [], reconnects = []
  let selecting = true
  const installer = new FirmwareInstaller('fake-esptool', {
    ports: async () => {
      events.push('ports')
      return device.ports.map(port => ({ ...port }))
    },
    identify: async port => {
      assert.equal(port, usbPort.port)
      events.push(selecting ? 'initial-identify' : 'fresh-identify')
      if (!selecting) {
        assert.equal(installer.state.busy, true, 'identity revalidation holds the installation lock')
        if (onIdentify) return onIdentify({ installer, device, events, calls })
      }
      return { ...device.identity }
    },
    run: async (_, args, options) => {
      assert.equal(argument(args, '--port'), usbPort.port)
      calls.push({ args, cwd: options.cwd })
      if (args.includes('flash-id')) {
        events.push('probe')
        const response = await onProbe?.({ installer, device, events, calls, args, options })
        return response ?? probeOutput
      }
      assert.ok(args.includes('write-flash'))
      events.push('write')
      return onWrite ? onWrite({ installer, device, events, calls, args, options }) : verified
    },
    reconnect: async (original, expected) => {
      events.push('reconnect')
      reconnects.push({ original, expected })
      return onReconnect ? onReconnect({ installer, device, events, calls, expected })
        : { ...device.identity, hardware_id: hardwareId, firmware_version: f.manifest.firmware_version }
    },
  })
  await installer.refreshPorts()
  installer.selectPort(usbPort.port)
  if (!manual) await installer.identifyFirmware(usbPort.port)
  const target = installer.captureInstallTarget(usbPort.port, board)
  await installer.select(f.directory, target)
  selecting = false
  return { installer, device, events, calls, reconnects, directory: f.directory }
}

async function install(installer, baud = 460800) {
  installer.start(usbPort.port, board, baud)
  await installer.completion
}
function assertNoWrites(calls) {
  assert.ok(!calls.some(call => call.args.includes('write-flash')), 'failed checks must prevent every firmware write')
}

test('ROM MAC bytes are converted to the firmware ESP.getEfuseMac hardware ID', () => {
  assert.equal(parseProbeHardwareId(probe), hardwareId)
  assert.equal(parseProbeHardwareId(probe.replace('08:a6:f7:23:8e:98', '08:A6:F7:23:8E:98')), hardwareId)
  assert.equal(parseProbeHardwareId(probe.replaceAll('\n', '\r\n')), hardwareId)
})

for (const [name, output] of [
  ['missing MAC', probe.replace('MAC: 08:a6:f7:23:8e:98\n', '')],
  ['incomplete MAC', probe.replace('08:a6:f7:23:8e:98', '08:a6:f7:23:8e')],
  ['nonhex MAC', probe.replace('08:a6:f7:23:8e:98', '08:a6:f7:23:8e:zz')],
  ['extra MAC byte', probe.replace('08:a6:f7:23:8e:98', '08:a6:f7:23:8e:98:00')],
  ['duplicate MAC', probe + 'MAC: 08:a6:f7:23:8e:98\n'],
  ['conflicting MAC', probe + 'MAC: 01:02:03:04:05:06\n'],
  ['duplicate malformed MAC', probe + 'MAC: not-a-mac\n'],
]) test(`strict ROM identity parser rejects ${name}`, () => {
  assert.throws(() => parseProbeHardwareId(output), /MAC|hardware|identity/i)
})

for (const baud of [115200, 460800]) test(`CYD at ${baud}: identifies before probing and preserves download mode until verified writing`, async t => {
  const { installer, events, calls, reconnects, directory } = await selectedCyd(t, {
    onProbe: async ({ installer, calls }) => {
      assert.equal(installer.state.stage, 'connecting')
      assert.equal(calls.length, 1)
      assert.throws(() => installer.start(usbPort.port, board, baud), /one installation/)
      // The immutable snapshot must survive source package changes while the
      // board is waiting for the next command in download mode.
      await writeFile(path.join(directory, 'app.bin'), 'changed after validation')
    },
    onWrite: async ({ installer, args, options }) => {
      assert.equal(installer.state.stage, 'writing_and_verifying')
      assert.equal((await readFile(path.join(options.cwd, 'app.bin'))).length, 128)
      assert.equal(argument(args, '--baud'), String(baud))
      assert.equal(argument(args, '--before'), 'no-reset')
      assert.equal(argument(args, '--after'), 'hard-reset')
      assert.ok(!args.includes('--erase-all') && !args.includes('--force'))
      options.onOutput(verified)
      return verified
    },
  })
  await install(installer, baud)
  assert.deepEqual(events.filter(event => event !== 'ports'), ['initial-identify', 'fresh-identify', 'probe', 'write', 'reconnect'])
  const afterProbe = events.slice(events.indexOf('probe') + 1, events.indexOf('write'))
  assert.ok(afterProbe.includes('ports'), 'USB descriptors must be checked again after probing')
  assert.ok(!afterProbe.includes('fresh-identify'), 'a firmware hello must not reset the waiting ROM loader')
  assert.equal(calls.length, 2)
  assert.equal(argument(calls[0].args, '--baud'), '115200')
  assert.equal(argument(calls[0].args, '--before'), 'default-reset')
  assert.equal(argument(calls[0].args, '--after'), 'no-reset-stub')
  assert.equal(argument(calls[0].args, '--connect-attempts'), '2')
  assert.equal(calls[0].cwd, calls[1].cwd)
  assert.equal(installer.state.stage, 'boot_verified')
  assert.equal(installer.state.busy, false)
  assert.equal(installer.state.progress.verified, 4)
  assert.equal(reconnects[0].expected.hardwareId, hardwareId)
  assert.equal(reconnects[0].expected.board, board)
  assert.equal(reconnects[0].expected.version, '1.1.42')
  await assert.rejects(access(calls[0].cwd))
})

for (const [name, output] of [
  ['missing MAC', probe.replace('MAC: 08:a6:f7:23:8e:98\n', '')],
  ['malformed MAC', probe.replace('08:a6:f7:23:8e:98', '08:a6:f7:23:8e:gg')],
  ['duplicate MAC', probe + 'MAC: 08:a6:f7:23:8e:98\n'],
  ['same-descriptor physical board swap', probe.replace('08:a6:f7:23:8e:98', '01:02:03:04:05:06')],
  ['insufficient flash', probe.replace('Detected flash size: 4MB', 'Detected flash size: 2MB')],
  ['wrong chip', probe.replace('ESP32-D0WD-V3', 'ESP32-S3')],
]) test(`CYD ${name} during the probe prevents writing`, async t => {
  const { installer, calls } = await selectedCyd(t, { probeOutput: output })
  await install(installer)
  assert.equal(installer.state.stage, 'failed')
  assert.equal(installer.state.busy, false)
  assertNoWrites(calls)
  assert.equal(calls.length, 1)
  await assert.rejects(access(calls[0].cwd))
})

for (const [name, change] of [
  ['hardware ID', identity => { identity.hardware_id = '112233445566' }],
  ['board target', identity => { identity.board_target = 'JC4827W543' }],
]) test(`CYD fresh ${name} mismatch is rejected before any esptool command`, async t => {
  const { installer, device, calls } = await selectedCyd(t)
  change(device.identity)
  await install(installer)
  assert.equal(installer.state.stage, 'failed')
  assertNoWrites(calls)
  assert.equal(calls.length, 0)
})

test('CYD update cannot fall back to manual installation when its identified firmware stops responding', async t => {
  const { installer, calls } = await selectedCyd(t, {
    onIdentify: async () => { throw Object.assign(new Error('No compatible firmware responded'), { code: 'USB_IDENTITY_TIMEOUT' }) },
  })
  await install(installer)
  assert.equal(installer.state.stage, 'failed')
  assert.equal(calls.length, 0)
  assertNoWrites(calls)
})

for (const [name, change] of [
  ['serial number', ports => { ports[0].serialNumber = 'replacement-cyd' }],
  ['vendor ID', ports => { ports[0].vendorId = '10c4' }],
  ['product ID', ports => { ports[0].productId = 'ea60' }],
  ['disappearance', ports => { ports.length = 0 }],
]) test(`CYD USB ${name} change after probing prevents writing`, async t => {
  const { installer, calls } = await selectedCyd(t, { onProbe: ({ device }) => change(device.ports) })
  await install(installer)
  assert.equal(installer.state.stage, 'failed')
  assert.equal(installer.state.busy, false)
  assert.equal(calls.length, 1)
  assertNoWrites(calls)
})

for (const code of ['USB_IDENTITY_TIMEOUT', 'USB_IDENTITY_UNSUPPORTED']) test(`manual CYD first installation accepts ${code} and pins the probed hardware ID for startup`, async t => {
  const { installer, events, calls, reconnects } = await selectedCyd(t, {
    manual: true,
    onIdentify: async () => { throw Object.assign(new Error('No compatible firmware responded'), { code }) },
  })
  await install(installer)
  assert.deepEqual(events.filter(event => event !== 'ports'), ['fresh-identify', 'probe', 'write', 'reconnect'])
  assert.equal(installer.state.stage, 'boot_verified')
  assert.equal(calls.length, 2)
  assert.equal(reconnects[0].expected.hardwareId, hardwareId)
})

test('manual CYD first installation rejects a serial-open error before probing', async t => {
  const { installer, calls } = await selectedCyd(t, {
    manual: true,
    onIdentify: async () => { throw Object.assign(new Error('Port is busy'), { code: 'EACCES' }) },
  })
  await install(installer)
  assert.equal(installer.state.stage, 'failed')
  assert.equal(calls.length, 0)
  assertNoWrites(calls)
})

test('CYD requires all four write verification messages before confirming startup', async t => {
  const { installer, calls, reconnects } = await selectedCyd(t, { onWrite: async () => 'Hash of data verified.\n'.repeat(3) })
  await install(installer)
  assert.equal(installer.state.stage, 'failed')
  assert.match(installer.state.error, /four verification/)
  assert.equal(calls.length, 2)
  assert.equal(reconnects.length, 0)
})

test('CYD verified writes stay successful when firmware startup cannot be confirmed', async t => {
  const { installer, reconnects } = await selectedCyd(t, { onReconnect: async () => { throw new Error('No firmware responded') } })
  await install(installer)
  assert.equal(installer.state.stage, 'written')
  assert.equal(installer.state.busy, false)
  assert.equal(installer.state.error, '')
  assert.match(installer.state.identityError, /startup was not confirmed/)
  assert.equal(reconnects[0].expected.hardwareId, hardwareId)
})

const wrongBootMode = () => esptoolFailure('Failed to connect to ESP32: Wrong boot mode detected (0x13)!', 2)
const noSerialData = () => Object.assign(new Error('Failed to connect to ESP32: No serial data received.'), { connectionFailed: true })
const probeCalls = calls => calls.filter(call => call.args.includes('flash-id'))
function deferred() {
  let resolve
  const promise = new Promise(complete => { resolve = complete })
  return { promise, resolve }
}

test('CYD wrong boot mode exposes a warning and keeps the operation locked before the longer manual probe', { timeout: 5000 }, async t => {
  const retryStarted = deferred(), retryFinished = deferred()
  const { installer, events, calls, reconnects } = await selectedCyd(t, {
    onProbe: async ({ installer, calls, args }) => {
      if (probeCalls(calls).length === 1) {
        assert.equal(installer.state.stage, 'connecting')
        assert.equal(installer.state.bootMode, null)
        assert.equal(argument(args, '--connect-attempts'), '2')
        throw wrongBootMode()
      }
      assert.equal(installer.snapshot().stage, 'connecting_manual')
      assert.equal(installer.snapshot().bootMode, '0x13')
      assert.equal(argument(args, '--connect-attempts'), '30')
      assert.equal(argument(args, '--before'), 'default-reset')
      assert.equal(argument(args, '--after'), 'no-reset-stub')
      retryStarted.resolve()
      await retryFinished.promise
    },
  })
  installer.start(usbPort.port, board, 460800)
  await retryStarted.promise
  assert.equal(installer.state.busy, true)
  assert.throws(() => installer.start(usbPort.port, board, 460800), /one installation/)
  assert.throws(() => installer.selectPort(usbPort.port), /Wait for USB/)
  await assert.rejects(installer.identifyFirmware(usbPort.port), /wait|available/i)
  assertNoWrites(calls)
  const probes = events.flatMap((event, index) => event === 'probe' ? [index] : [])
  assert.equal(probes.length, 2)
  const betweenProbes = events.slice(probes[0] + 1, probes[1])
  assert.ok(betweenProbes.includes('ports'), 'revalidate the original USB descriptors before the fallback probe')
  assert.ok(!betweenProbes.includes('fresh-identify'), 'the download-mode retry must not demand running app firmware')
  retryFinished.resolve()
  await installer.completion
  assert.equal(installer.state.stage, 'boot_verified')
  assert.equal(installer.state.busy, false)
  assert.equal(probeCalls(calls).length, 2)
  assert.equal(calls.filter(call => call.args.includes('write-flash')).length, 1)
  assert.equal(events.filter(event => event === 'fresh-identify').length, 1)
  assert.equal(argument(calls.find(call => call.args.includes('write-flash')).args, '--before'), 'no-reset')
  assert.equal(reconnects[0].expected.hardwareId, hardwareId)
})

for (const [name, failure] of [
  ['another wrong boot mode', wrongBootMode],
  ['another recognized connection failure', noSerialData],
]) test(`CYD retry is bounded when the longer probe fails with ${name}`, async t => {
  const { installer, calls } = await selectedCyd(t, {
    onProbe: ({ calls }) => { throw probeCalls(calls).length === 1 ? wrongBootMode() : failure() },
  })
  await install(installer)
  assert.equal(installer.state.stage, 'failed')
  assert.equal(installer.state.busy, false)
  assert.equal(probeCalls(calls).length, 2)
  assertNoWrites(calls)
  await assert.rejects(access(calls[0].cwd))
})

test('CYD recognized no-data connection failure gets a long fallback without a wrong-boot warning', async t => {
  const { installer, calls, events } = await selectedCyd(t, {
    onProbe: ({ installer, calls, args }) => {
      if (probeCalls(calls).length === 1) throw noSerialData()
      assert.equal(installer.state.stage, 'connecting')
      assert.equal(installer.state.bootMode, null)
      assert.equal(argument(args, '--connect-attempts'), '30')
      assert.equal(argument(args, '--after'), 'no-reset-stub')
    },
  })
  await install(installer)
  assert.equal(installer.state.stage, 'boot_verified')
  assert.equal(probeCalls(calls).length, 2)
  assert.equal(events.filter(event => event === 'fresh-identify').length, 1)
})

for (const [name, error] of [
  ['serial port-open failure', Object.assign(new Error('Access denied opening COM13'), { code: 'EACCES' })],
  ['process launch failure', Object.assign(new Error('spawn fake-esptool ENOENT'), { code: 'ENOENT' })],
  ['unrecognized esptool failure', esptoolFailure('Unexpected internal process error', 1)],
]) test(`CYD ${name} is not retried`, async t => {
  const { installer, calls } = await selectedCyd(t, { onProbe: () => { throw error } })
  await install(installer)
  assert.equal(installer.state.stage, 'failed')
  assert.equal(installer.state.busy, false)
  assert.equal(probeCalls(calls).length, 1)
  assertNoWrites(calls)
})

for (const [name, change] of [
  ['descriptor replacement', device => { device.ports[0].serialNumber = 'different-board' }],
  ['port disappearance', device => { device.ports = [] }],
]) test(`CYD ${name} after the initial failure prevents even the fallback probe`, async t => {
  const { installer, calls } = await selectedCyd(t, {
    onProbe: ({ device }) => { change(device); throw wrongBootMode() },
  })
  await install(installer)
  assert.equal(installer.state.stage, 'failed')
  assert.equal(probeCalls(calls).length, 1)
  assertNoWrites(calls)
})

for (const [name, response] of [
  ['USB descriptor replacement', ({ device }) => { device.ports[0].serialNumber = 'different-board'; return probe }],
  ['same-descriptor ROM MAC replacement', () => probe.replace('08:a6:f7:23:8e:98', '01:02:03:04:05:06')],
  ['missing ROM MAC', () => probe.replace('MAC: 08:a6:f7:23:8e:98\n', '')],
]) test(`CYD ${name} during the fallback still prevents writing`, async t => {
  const { installer, calls, events } = await selectedCyd(t, {
    onProbe: context => {
      if (probeCalls(context.calls).length === 1) throw wrongBootMode()
      return response(context)
    },
  })
  await install(installer)
  assert.equal(installer.state.stage, 'failed')
  assert.equal(installer.state.busy, false)
  assert.equal(probeCalls(calls).length, 2)
  assert.equal(events.filter(event => event === 'fresh-identify').length, 1)
  assertNoWrites(calls)
})

test('manual CYD first installation pins the retry probe MAC when old firmware cannot identify itself', async t => {
  const { installer, calls, events, reconnects } = await selectedCyd(t, {
    manual: true,
    onIdentify: async () => { throw Object.assign(new Error('No compatible firmware responded'), { code: 'USB_IDENTITY_TIMEOUT' }) },
    onProbe: ({ calls }) => { if (probeCalls(calls).length === 1) throw wrongBootMode() },
  })
  await install(installer)
  assert.equal(installer.state.stage, 'boot_verified')
  assert.equal(events.filter(event => event === 'fresh-identify').length, 1)
  assert.equal(probeCalls(calls).length, 2)
  assert.equal(reconnects[0].expected.hardwareId, hardwareId)
})

test('non-CYD recognized connection fallback keeps the shorter seven-attempt window and existing reset behavior', async t => {
  const boardTarget = 'JC4827W543'
  const f = await fixture(t, boardTarget)
  const calls = []
  let identities = 0
  const identity = { ...installedIdentity, board_target: boardTarget }
  const installer = new FirmwareInstaller('fake-esptool', {
    ports: async () => [{ ...usbPort }],
    identify: async () => { identities++; return { ...identity } },
    run: async (_, args) => {
      calls.push({ args })
      if (args.includes('flash-id')) {
        assert.equal(installer.state.stage, 'connecting')
        assert.equal(installer.state.bootMode, null)
        assert.equal(argument(args, '--after'), 'hard-reset')
        assert.equal(argument(args, '--before'), 'default-reset')
        if (probeCalls(calls).length === 1) {
          assert.equal(argument(args, '--connect-attempts'), '2')
          throw noSerialData()
        }
        assert.equal(argument(args, '--connect-attempts'), '7')
        return 'Chip type: ESP32-S3 (revision v0.2)\nDetected flash size: 4MB\n'
      }
      assert.equal(argument(args, '--before'), 'default-reset')
      assert.equal(argument(args, '--after'), 'hard-reset')
      return verified
    },
  })
  await installer.refreshPorts()
  installer.selectPort(usbPort.port)
  await installer.identifyFirmware(usbPort.port)
  await installer.select(f.directory, installer.captureInstallTarget(usbPort.port, boardTarget))
  installer.start(usbPort.port, boardTarget, 460800)
  await installer.completion
  assert.equal(installer.state.stage, 'written')
  assert.equal(installer.state.busy, false)
  assert.equal(probeCalls(calls).length, 2)
  assert.equal(calls.filter(call => call.args.includes('write-flash')).length, 1)
  assert.equal(identities, 2, 'non-CYD identification remains after probing')
})
