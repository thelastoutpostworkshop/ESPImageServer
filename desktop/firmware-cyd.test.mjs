import test from 'node:test'
import assert from 'node:assert/strict'
import { mkdtemp, writeFile, readFile, rm, access } from 'node:fs/promises'
import os from 'node:os'
import path from 'node:path'
import { createHash } from 'node:crypto'
import { FirmwareInstaller, parseProbeHardwareId } from './firmware.mjs'

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
async function fixture(t) {
  const directory = await mkdtemp(path.join(os.tmpdir(), 'espimage-cyd-test-'))
  t.after(() => rm(directory, { recursive: true, force: true }))
  const image = Buffer.alloc(128)
  image[0] = 0xe9
  image.writeUInt16LE(0, 12)
  const table = Buffer.alloc(96, 255)
  table.writeUInt16LE(0x50aa); table[2] = 0; table[3] = 0
  table.writeUInt32LE(0x10000, 4); table.writeUInt32LE(0x300000, 8)
  const manifest = {
    schema_version: 1, package_type: 'esp-image-display-firmware', installation_type: 'first_install',
    board_target: board, chip: 'esp32', firmware_version: '1.1.42',
    flash: { mode: 'dio', frequency: '80m', size_bytes: 4194304 }, segments: [],
  }
  for (const [role, file, offset, data] of [
    ['bootloader', 'boot.bin', '0x1000', image],
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
        await onProbe?.({ installer, device, events, calls, args, options })
        return probeOutput
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
  assert.equal(argument(calls[0].args, '--connect-attempts'), '30')
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
