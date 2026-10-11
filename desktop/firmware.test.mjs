import test from 'node:test'
import assert from 'node:assert/strict'
import { mkdtemp, writeFile, readFile, rm, access } from 'node:fs/promises'
import os from 'node:os'
import path from 'node:path'
import { createHash } from 'node:crypto'
import { FirmwareInstaller, parseProbe, validatePackage, writeArguments, runProcess, esptoolFailure } from './firmware.mjs'
import { firmwareProgress } from './firmware-progress.mjs'

test('upload progress handles split chunks, carriage returns, and differently sized binaries', () => {
  const updates = []
  const progress = firmwareProgress([{ size_bytes: 10 }, { size_bytes: 90 }], value => updates.push(value))
  progress.push('Writing at 0x00000000... (100 %)\r\nHash of data veri')
  assert.equal(updates.at(-1).percent, 10)
  progress.push('fied.\nWriting at 0x00010000 [====] 50.0% 45/90 bytes\r')
  assert.equal(updates.at(-1).percent, 55)
  assert.equal(updates.at(-1).verified, 1)
  progress.push('Writing at 0x00010000 [====] 40.0%\rWriting at 0x00010000 [====] 100.0%\rWrote 90 bytes\n')
  assert.equal(updates.at(-1).phase, 'verifying')
  assert.equal(updates.at(-1).verified, 1)
  progress.push('Hash of data verified.')
  progress.finish()
  assert.deepEqual(updates.at(-1), { percent: 100, verified: 2, total: 2, phase: 'verified' })
  assert.ok(updates.every((value, i) => i === 0 || value.percent >= updates[i - 1].percent))
})

const sha = data => createHash('sha256').update(data).digest('hex')
async function fixture(t) {
  const directory = await mkdtemp(path.join(os.tmpdir(), 'espimage-test-'))
  t.after(() => rm(directory, { recursive: true, force: true }))
  const image = Buffer.alloc(128); image[0] = 0xe9; image.writeUInt16LE(9, 12)
  const table = Buffer.alloc(96, 255)
  table.writeUInt16LE(0x50aa); table[2] = 0; table[3] = 0
  table.writeUInt32LE(0x10000, 4); table.writeUInt32LE(0x300000, 8)
  const definitions = [
    ['bootloader', 'boot.bin', '0x0', image],
    ['partition_table', 'partitions.bin', '0x8000', table],
    ['ota_data', 'boot_app0.bin', '0xe000', Buffer.alloc(8192)],
    ['application', 'app.bin', '0x10000', image]
  ]
  const manifest = { schema_version: 1, package_type: 'esp-image-display-firmware', installation_type: 'first_install',
    board_target: 'JC4827W543', chip: 'esp32s3', firmware_version: '1.1.1',
    flash: { mode: 'dio', frequency: '80m', size_bytes: 4194304 }, segments: [] }
  for (const [role, file, offset, data] of definitions) {
    await writeFile(path.join(directory, file), data)
    manifest.segments.push({ role, file, offset, size_bytes: data.length, sha256: sha(data) })
  }
  const save = () => writeFile(path.join(directory, 'manifest.json'), JSON.stringify(manifest))
  await save()
  return { directory, manifest, save }
}
const probe = 'Chip type: ESP32-S3 (revision v0.2)\nDetected flash size: 4MB\n'
const verified = 'Hash of data verified.\n'.repeat(4) + 'Hard resetting via RTS pin...\n'

test('refreshing USB status preserves identity until completion and rejects a swapped board', async () => {
  const original={port:'COM8',hardware_id:'aabbccddeeff',wifi_connected:false}
  const installer=new FirmwareInstaller('unused',{ports:async()=>[{port:'COM8'}],identify:async()=>({...original,wifi_connected:true})})
  installer.state.identity=original;installer.state.selectedPort='COM8'
  assert.equal((await installer.refreshIdentity('COM8')).identity.wifi_connected,true)
  installer.identify=async()=>({...original,hardware_id:'112233445566'})
  const swapped=await installer.refreshIdentity('COM8')
  assert.equal(swapped.identity,null);assert.match(swapped.identityError,/changed/)
  await assert.rejects(installer.refreshIdentity('COM9'),/Identify/)
})

test('valid package keeps binary hashes and uses structured arguments without full erase', async t => {
  const f = await fixture(t), pkg = await validatePackage(f.directory)
  const args = writeArguments(pkg.manifest, 'COM8', pkg.segments)
  assert.equal(pkg.segments.length, 4)
  assert.equal(args[args.indexOf('write-flash') + 1], '--flash-mode')
  assert.ok(!args.includes('--erase-all') && !args.includes('--force'))
  assert.deepEqual(args.slice(-2), ['0x10000', 'app.bin'])
})
for (const [name, change, message] of [
  ['prerelease version', m => { m.firmware_version = '1.2.0-beta' }, /version/],
  ['build suffix', m => { m.firmware_version = '1.2.0+build' }, /version/],
  ['unsafe path', m => { m.segments[0].file = '../boot.bin' }, /filename/],
  ['overlap', m => { m.segments[3].offset = '0xe000' }, /overlap/],
  ['overflow', m => { m.segments[3].offset = '0x400000' }, /capacity/],
  ['missing component', m => { m.segments.pop() }, /four/],
  ['repeated role', m => { m.segments[3].role = 'bootloader' }, /role/],
  ['chip mismatch', m => { m.chip = 'esp32c6' }, /chip/],
  ['invalid hash', m => { m.segments[3].sha256 = 'a'.repeat(64) }, /Checksum/],
  ['wrong layout', m => { m.segments[3].offset = '0x20000' }, /layout/]
]) test(`rejects ${name}`, async t => {
  const f = await fixture(t); change(f.manifest); await f.save()
  await assert.rejects(validatePackage(f.directory), message)
})
test('rejects an ESP image for a different chip even with matching checksum', async t => {
  const f = await fixture(t), file = path.join(f.directory, 'app.bin')
  const data = await readFile(file); data.writeUInt16LE(13, 12)
  await writeFile(file, data); f.manifest.segments[3].sha256 = sha(data); await f.save()
  await assert.rejects(validatePackage(f.directory), /incompatible ESP image/)
})
test('rejects application exceeding the actual app partition', async t => {
  const f = await fixture(t), file = path.join(f.directory, 'partitions.bin')
  const data = await readFile(file); data.writeUInt32LE(64, 8)
  await writeFile(file, data); f.manifest.segments[1].sha256 = sha(data); await f.save()
  await assert.rejects(validatePackage(f.directory), /partition table/)
})
test('rejects partition metadata padding that would erase NVS settings', async t => {
  const f = await fixture(t), file = path.join(f.directory, 'partitions.bin')
  const data = Buffer.alloc(8192); (await readFile(file)).copy(data)
  await writeFile(file, data)
  Object.assign(f.manifest.segments[1], { size_bytes: data.length, sha256: sha(data) }); await f.save()
  await assert.rejects(validatePackage(f.directory), /reserved settings/)
})
test('probe checks actual chip and capacity', () => {
  assert.equal(parseProbe(probe, 'esp32s3', 4194304).flashBytes, 4194304)
  assert.equal(parseProbe('Chip type: ESP32-D0WD-V3 (revision v3.1)\nDetected flash size: 4MB', 'esp32', 4194304).chip, 'esp32')
  assert.throws(() => parseProbe('Chip type: ESP32-C3\nDetected flash size: 4MB', 'esp32', 4194304), /chip/)
  assert.throws(() => parseProbe(probe, 'esp32c6', 4194304), /chip/)
  assert.throws(() => parseProbe(probe, 'esp32s3', 16777216), /capacity/)
  assert.throws(() => parseProbe('unknown output', 'esp32s3', 4194304))
})

test('ESP32-C6FH4 probe is recognized as C6 while chip and capacity checks remain enforced', () => {
  const output = 'Connected to ESP32-C6 on COM3:\nChip type: ESP32-C6FH4 (QFN32) (revision v0.1)\nDetected flash size: 4MB\n'
  assert.deepEqual(parseProbe(output, 'esp32c6', 4194304), {chip:'esp32c6',flashBytes:4194304})
  assert.throws(() => parseProbe(output, 'esp32s3', 4194304), /ESP32-C6FH4.*ESP32-S3/)
  assert.throws(() => parseProbe(output, 'esp32c6', 8388608), /capacity/)
  assert.throws(() => parseProbe(output.replace('Chip type: ESP32-C6FH4', 'Chip type: ESP32-C61'), 'esp32c6', 4194304), /chip/)
  assert.throws(() => parseProbe(output.replace('Detected flash size: 4MB', ''), 'esp32c6', 4194304), /capacity/)
})
for (const portName of ['COM8', '/dev/ttyUSB0', '/dev/ttyACM0', '/dev/cu.usbmodem1101']) test(`${portName}: install stages immutable files, verifies four writes, and cleans up`, async t => {
  const f = await fixture(t), calls = []
  const installer = new FirmwareInstaller('fake', {
    ports: async () => [{ port: portName }],
    run: async (_, args, options) => {
      assert.equal(args[args.indexOf('--port') + 1], portName)
      calls.push({ args, cwd: options.cwd })
      if (args.includes('flash-id')) {
        await writeFile(path.join(f.directory, 'app.bin'), 'changed after validation')
        return probe
      }
      assert.notEqual(options.cwd, f.directory)
      assert.equal((await readFile(path.join(options.cwd, 'app.bin'))).length, 128)
      return verified
    }
  })
  await installer.select(f.directory)
  installer.start(portName, 'JC4827W543', 460800)
  assert.throws(() => installer.start(portName, 'JC4827W543', 460800), /one installation/)
  await installer.completion
  assert.equal(installer.state.stage, 'written'); assert.equal(installer.state.busy, false)
  assert.equal(calls.length, 2)
  await assert.rejects(access(calls[0].cwd))
})
for (const [name, reply, count] of [
  ['insufficient flash', 'Chip type: ESP32-S3 (revision v0.2)\nDetected flash size: 2MB\n', 1],
  ['missing verification', probe, 2]
]) test(`failed ${name} never reports success`, async t => {
  const f = await fixture(t); let calls = 0
  const installer = new FirmwareInstaller('fake', { ports: async () => [{ port: 'COM8' }],
    run: async () => (++calls === 1 ? reply : 'Wrote bytes but no verification') })
  await installer.select(f.directory); installer.start('COM8', 'JC4827W543', 115200)
  await installer.completion
  assert.equal(installer.state.stage, 'failed'); assert.equal(installer.state.busy, false)
  assert.equal(calls, count)
})
test('modified package and unplugged port are rejected before esptool runs', async t => {
  const f = await fixture(t); let calls = 0
  const installer = new FirmwareInstaller('fake', { ports: async () => [], run: async () => { calls++ } })
  await installer.select(f.directory)
  f.manifest.firmware_version = '2.0.0'; await f.save()
  installer.start('COM8', 'JC4827W543', 460800); await installer.completion
  assert.match(installer.state.error, /changed/)
  await installer.select(f.directory)
  installer.start('COM8', 'JC4827W543', 460800); await installer.completion
  assert.match(installer.state.error, /no longer available/); assert.equal(calls, 0)
})
test('failed process releases the busy state and allows retry', async t => {
  const f = await fixture(t)
  const installer = new FirmwareInstaller('fake', { ports: async () => [{ port: 'COM8' }], run: async () => { throw new Error('Port is busy') } })
  await installer.select(f.directory); installer.start('COM8', 'JC4827W543', 460800)
  await installer.completion
  assert.equal(installer.state.busy, false); assert.match(installer.state.error, /Port is busy/)
  await installer.select(f.directory)
  assert.equal(installer.state.stage, 'ready')
})
test('successful writes remain successful when old firmware cannot identify itself', async t => {
  const f = await fixture(t)
  const installer = new FirmwareInstaller('fake', { ports: async () => [{ port: 'COM8' }],
    run: async (_, args) => args.includes('flash-id') ? probe : verified,
    reconnect: async () => { throw new Error('No compatible firmware responded') } })
  await installer.select(f.directory); installer.start('COM8', 'JC4827W543', 460800); await installer.completion
  assert.equal(installer.state.stage, 'written')
  assert.match(installer.state.identityError, /startup was not confirmed/)
  assert.equal(installer.state.error, '')
})
test('installer publishes live progress, separates startup checks, and clears progress for a retry', async t => {
  const f = await fixture(t)
  const installer = new FirmwareInstaller('fake', { ports: async () => [{ port: 'COM8' }],
    run: async (_, args, options) => {
      if (args.includes('flash-id')) {
        assert.equal(installer.snapshot().progress, null)
        options.onOutput('Hard resetting via RTS pin...\n')
        assert.equal(installer.state.stage, 'connecting')
        return probe
      }
      options.onOutput('Writing at 0x00000000... (50 %)\r')
      assert.ok(installer.snapshot().progress.percent > 0)
      assert.ok(installer.snapshot().progress.percent < 50)
      assert.equal(installer.state.stage, 'writing_and_verifying')
      options.onOutput(verified)
      assert.equal(installer.state.stage, 'restarting')
      return verified
    }, reconnect: async () => {
      assert.equal(installer.state.stage, 'identifying')
      assert.equal(installer.snapshot().progress.percent, 100)
      throw new Error('Not yet connected')
    } })
  await installer.select(f.directory)
  installer.start('COM8', 'JC4827W543', 460800)
  await installer.completion
  assert.equal(installer.state.stage, 'written')
  await installer.select(f.directory)
  assert.equal(installer.snapshot().progress, null)
})

test('identification shares the flash operation lock and releases it on errors', async t => {
  const f = await fixture(t)
  let finish
  const installer = new FirmwareInstaller('fake', { ports: async () => [{ port: 'COM8' }], identify: () => new Promise(resolve => { finish = resolve }) })
  await installer.select(f.directory)
  const checking = installer.identifyFirmware('COM8')
  assert.throws(() => installer.start('COM8', 'JC4827W543', 460800), /one installation/)
  await Promise.resolve()
  finish({ hardware_id: 'aabbccddeeff', port: 'COM8' }); await checking
  assert.equal(installer.state.busy, false)
})
test('process runner handles chunked output, errors and timeouts without hardware', async () => {
  const output = await runProcess(process.execPath, ['-e', 'process.stdout.write("one");process.stderr.write("two")'])
  assert.ok(output.includes('one') && output.includes('two'))
  await assert.rejects(runProcess(process.execPath, ['-e', 'process.exit(1)']), /failed/)
  await assert.rejects(runProcess(process.execPath, ['-e', 'setInterval(()=>{},1000)'], { timeout: 100 }), /timed out/)
})

for (const [description, output, bootMode] of [
  ['normal ESP32 log', 'A fatal error occurred: Failed to connect to ESP32: Wrong boot mode detected (0x13)! The chip needs to be in download mode.\n', '0x13'],
  ['CRLF log', 'esptool v5.1.0\r\nSerial port COM13:\r\nConnecting...\r\nWrong boot mode detected (0x17)!\r\n', '0x17'],
  ['uppercase boot mode', 'Wrong boot mode detected (0X2A)!', '0x2a'],
]) test(`wrong boot mode in ${description} gives actionable BOOT and RESET guidance`, () => {
  const error = esptoolFailure(output, 2)
  assert.ok(error instanceof Error)
  assert.equal(error.code, 'ESPTOOL_WRONG_BOOT_MODE')
  assert.equal(error.bootMode, bootMode)
  assert.match(error.message, /not in download mode/i)
  assert.ok(error.message.includes(bootMode))
  assert.match(error.message, /BOOT/)
  assert.match(error.message, /RESET\/EN/)
  assert.match(error.message, /release BOOT/i)
  assert.match(error.message, /release BOOT and press RESET\/EN once, then retry installation/i)
  assert.match(error.message, /wait for.*Connecting to your display.*hold BOOT.*press and release RESET\/EN.*then release BOOT/i)
})

for (const output of [
  'A fatal error occurred: Failed to connect to ESP32: No serial data received.',
  'Failed to connect to ESP32: Invalid head of packet (0x13): Possible serial noise or corruption.',
  'A fatal error occurred: Failed to connect to ESP32: Download mode successfully detected, but getting no sync reply.',
  'Wrong boot mode detected (unknown)!',
]) test(`unrelated connection failure remains generic: ${output}`, () => {
  const error = esptoolFailure(output, 2)
  assert.ok(error instanceof Error)
  assert.equal(error.code, undefined)
  assert.equal(error.bootMode, undefined)
  assert.equal(error.message, 'esptool failed (2). Check the log, USB cable, and whether another app holds the port.')
})

test('process runner translates a nonzero wrong-boot failure from normalized chunked ANSI and CRLF output', async () => {
  const chunks = []
  const first = '\x1b[31mesptool v5.1.0\r\nConnecting...\r\nA fatal error occurred: Failed to connect to ESP32: Wrong bo'
  const second = 'ot mode detected (0x13)! The chip needs to be in download mode.\x1b[0m\r\n'
  const script = `process.stdout.write(${JSON.stringify(first)}, () => { setImmediate(() => { process.stdout.write(${JSON.stringify(second)}); process.exitCode = 2 }) })`
  await assert.rejects(runProcess(process.execPath, ['-e', script], { onOutput: chunk => chunks.push(chunk) }), error => {
    assert.equal(error.code, 'ESPTOOL_WRONG_BOOT_MODE')
    assert.equal(error.bootMode, '0x13')
    assert.match(error.message, /BOOT/)
    assert.match(error.message, /RESET\/EN/)
    return true
  })
  const log = chunks.join('')
  assert.match(log, /Wrong boot mode detected \(0x13\)/)
  assert.match(log, /\r\n/)
  assert.ok(!log.includes('\x1b'), 'ANSI color sequences must be removed before failure interpretation')
})

test('USB port disappearance or replacement invalidates identity and Wi-Fi state', async () => {
  let ports = [{ port: 'COM8', serialNumber: 'one', vendorId: '303a', productId: '1001' }]
  const installer = new FirmwareInstaller('fake', { ports: async () => ports,
    identify: async port => ({ port, hardware_id: 'aabbccddeeff' }) })
  await installer.refreshPorts(); await installer.identifyFirmware('COM8')
  installer.state.wifi = { stage: 'connected' }
  ports = [{ ...ports[0], serialNumber: 'two' }]
  await installer.refreshPorts()
  assert.equal(installer.state.identity, null); assert.equal(installer.state.wifi, null)
  await installer.identifyFirmware('COM8')
  ports = []; await installer.refreshPorts()
  assert.equal(installer.state.identity, null)
  ports = [{ port: 'COM8', serialNumber: 'one' }]; await installer.refreshPorts()
  assert.equal(installer.state.identity, null, 'replug does not silently reuse the previous identity')
})
test('selecting another USB port clears setup state and cannot interrupt a flash', () => {
  const installer = new FirmwareInstaller('fake')
  installer.state.identity = { port: 'COM8' }; installer.state.wifi = { stage: 'connected' }
  installer.knownPorts = [{ port: 'COM8' }, { port: 'COM9' }]
  installer.selectPort('COM9')
  assert.equal(installer.state.identity, null); assert.equal(installer.state.wifi, null)
  installer.state.busy = true
  assert.throws(() => installer.selectPort('COM8'), /Wait for USB/)
})


test('AMOLED packages validate as ESP32-S3 and reject a different physical board', async t => {
  const f = await fixture(t)
  f.manifest.board_target = 'ESP32_S3_AMOLED_143'
  f.manifest.flash.size_bytes = 16 * 1048576
  await f.save()
  const pkg = await validatePackage(f.directory)
  assert.equal(pkg.manifest.chip, 'esp32s3')
  const installer = new FirmwareInstaller('unused')
  await installer.select(f.directory)
  assert.throws(() => installer.start('COM3', 'JC4827W543', 115200), /matching physical board/)
})

const usbDisplay = { port: 'COM8', serialNumber: 'original-usb', vendorId: '303a', productId: '1001' }
const installedIdentity = {
  port: 'COM8', hardware_id: 'aabbccddeeff', board_target: 'JC4827W543', board_name: 'Original display',
  firmware_version: '1.1.0', protocol_version: 1, capabilities: ['hello', 'status'], width: 480, height: 272,
  wifi_configured: false, wifi_connected: false,
}

function deferred() {
  let resolve
  const promise = new Promise(complete => { resolve = complete })
  return { promise, resolve }
}

// All USB enumeration, identification, esptool runs, and reconnects below are
// fake. Real package staging keeps cleanup and ordering checks representative.
async function selectedUsbPackage(t, { manual = false, onProbe, onFinalIdentify } = {}) {
  const f = await fixture(t)
  const device = { ports: [{ ...usbDisplay }], identity: { ...installedIdentity } }
  const events = [], calls = [], reconnects = []
  let selecting = true
  const installer = new FirmwareInstaller('fake', {
    ports: async () => device.ports.map(port => ({ ...port })),
    identify: async port => {
      events.push(selecting ? 'initial-identify' : 'final-identify')
      assert.equal(port, device.identity.port)
      if (!selecting) {
        assert.equal(installer.state.busy, true, 'the final identity check shares the installation lock')
        if (onFinalIdentify) return onFinalIdentify({ installer, device, events, calls })
      }
      return { ...device.identity }
    },
    run: async (_, args, options) => {
      calls.push({ args, cwd: options.cwd })
      if (args.includes('flash-id')) {
        events.push('probe')
        await onProbe?.({ installer, device, events, calls })
        return probe
      }
      assert.ok(args.includes('write-flash'))
      events.push('write')
      return verified
    },
    reconnect: async (original, expected) => {
      events.push('reconnect')
      reconnects.push({ original, expected })
      return { ...device.identity, firmware_version: f.manifest.firmware_version }
    },
  })
  await installer.refreshPorts()
  installer.selectPort('COM8')
  if (!manual) {
    await installer.identifyFirmware('COM8')
    assert.equal(installer.state.identity.hardware_id, installedIdentity.hardware_id)
  }
  const target = await installer.captureInstallTarget('COM8', 'JC4827W543')
  await installer.select(f.directory, target)
  selecting = false
  return { installer, device, events, calls, reconnects, directory: f.directory }
}

async function installSelected(installer) {
  installer.start('COM8', 'JC4827W543', 460800)
  await installer.completion
}

function assertNoFirmwareWrites(calls) {
  assert.ok(!calls.some(call => call.args.includes('write-flash')), 'identity failures must prevent every firmware write')
}

for (const [description, change] of [
  ['different hardware ID with unchanged USB descriptors', device => { device.identity.hardware_id = '112233445566' }],
  ['another S3 board target with the same hardware ID', device => { device.identity.board_target = 'ST7701_320X820' }],
  ['AMOLED board target with the same hardware ID', device => { device.identity.board_target = 'ESP32_S3_AMOLED_143' }],
]) test(`final USB check rejects ${description} after the chip probe`, async t => {
  const { installer, calls } = await selectedUsbPackage(t, { onProbe: ({ device }) => change(device) })
  await installSelected(installer)
  assert.equal(installer.state.stage, 'failed')
  assert.equal(installer.state.busy, false)
  assert.match(installer.state.error, /changed|match|identity|board/i)
  assertNoFirmwareWrites(calls)
  assert.equal(calls.length, 1)
  await assert.rejects(access(calls[0].cwd))
})

test('fresh USB identity succeeds after the probe without requiring unchanged Wi-Fi or installed version', async t => {
  const { installer, events, reconnects } = await selectedUsbPackage(t, {
    onProbe: ({ device }) => { device.identity.wifi_connected = true; device.identity.firmware_version = '1.0.9' },
  })
  await installSelected(installer)
  assert.deepEqual(events, ['initial-identify', 'probe', 'final-identify', 'write', 'reconnect'])
  assert.equal(installer.state.stage, 'boot_verified')
  assert.equal(installer.state.busy, false)
  assert.equal(reconnects[0].expected.hardwareId, installedIdentity.hardware_id)
  assert.equal(reconnects[0].expected.board, 'JC4827W543')
  assert.equal(reconnects[0].expected.version, '1.1.1')
})

test('an identified display that no longer answers cannot fall back to manual installation', async t => {
  const { installer, calls } = await selectedUsbPackage(t, {
    onFinalIdentify: async () => { throw new Error('USB identification timed out') },
  })
  await installSelected(installer)
  assert.equal(installer.state.stage, 'failed')
  assert.equal(installer.state.busy, false)
  assert.match(installer.state.error, /identif|check|respond|timed out/i)
  assertNoFirmwareWrites(calls)
  await assert.rejects(access(calls[0].cwd))
})

test('an identified installation cannot skip revalidation when its identity provider is unavailable', async t => {
  const { installer, calls } = await selectedUsbPackage(t)
  installer.identify = null
  await installSelected(installer)
  assert.equal(installer.state.stage, 'failed')
  assertNoFirmwareWrites(calls)
})

test('clearing cached identity does not remove the original identity bound to the selected package', async t => {
  const { installer, device, calls } = await selectedUsbPackage(t)
  installer.state.identity = null
  device.identity.hardware_id = '112233445566'
  await installSelected(installer)
  assert.equal(installer.state.stage, 'failed')
  assertNoFirmwareWrites(calls)
})

for (const [description, change] of [
  ['USB serial number', port => { port.serialNumber = 'replacement-usb' }],
  ['USB vendor ID', port => { port.vendorId = '10c4' }],
  ['USB product ID', port => { port.productId = 'ea60' }],
]) test(`changed ${description} is rejected before firmware writes`, async t => {
  const { installer, calls } = await selectedUsbPackage(t, { onProbe: ({ device }) => change(device.ports[0]) })
  await installSelected(installer)
  assert.equal(installer.state.stage, 'failed')
  assertNoFirmwareWrites(calls)
})

for (const replacement of [[], [{ ...usbDisplay, serialNumber: 'replacement-usb' }]]) {
  test(`port ${replacement.length ? 'replacement' : 'disappearance'} during the final identity await prevents writing`, { timeout: 5000 }, async t => {
    const identifying = deferred(), answer = deferred()
    const { installer, device, calls } = await selectedUsbPackage(t, {
      onFinalIdentify: async ({ device: current }) => { identifying.resolve(); await answer.promise; return { ...current.identity } },
    })
    installer.start('COM8', 'JC4827W543', 460800)
    await identifying.promise
    device.ports = replacement
    answer.resolve()
    await installer.completion
    assert.equal(installer.state.stage, 'failed')
    assert.equal(installer.state.busy, false)
    assertNoFirmwareWrites(calls)
  })
}

test('the installation lock remains held until the final USB identity check completes', { timeout: 5000 }, async t => {
  const identifying = deferred(), answer = deferred()
  const { installer } = await selectedUsbPackage(t, {
    onFinalIdentify: async ({ device }) => { identifying.resolve(); await answer.promise; return { ...device.identity } },
  })
  installer.start('COM8', 'JC4827W543', 460800)
  await identifying.promise
  assert.throws(() => installer.selectPort('COM8'), /Wait for USB/)
  assert.throws(() => installer.start('COM8', 'JC4827W543', 460800), /one installation/)
  await assert.rejects(installer.identifyFirmware('COM8'), /wait|available/i)
  answer.resolve()
  await installer.completion
  assert.equal(installer.state.stage, 'boot_verified')
  assert.equal(installer.state.busy, false)
})

for (const code of ['USB_IDENTITY_TIMEOUT', 'USB_IDENTITY_UNSUPPORTED']) test(`explicit manual first installation remains available after ${code}`, async t => {
  const { installer, calls } = await selectedUsbPackage(t, {
    manual: true, onFinalIdentify: async () => {
      throw Object.assign(new Error('No compatible firmware responded'), { code })
    },
  })
  await installSelected(installer)
  assert.equal(installer.state.stage, 'boot_verified')
  assert.equal(calls.filter(call => call.args.includes('write-flash')).length, 1)
})

test('manual installation rejects a responding display with the wrong board target', async t => {
  const { installer, device, calls } = await selectedUsbPackage(t, { manual: true })
  device.identity.board_target = 'ST7701_320X820'
  await installSelected(installer)
  assert.equal(installer.state.stage, 'failed')
  assertNoFirmwareWrites(calls)
})

for (const [description, code] of [
  ['malformed identity', 'USB_IDENTITY_INVALID'],
  ['port-open failure', 'EACCES'],
  ['serial close failure', 'EIO'],
]) test(`manual installation does not ignore ${description}`, async t => {
  const { installer, calls } = await selectedUsbPackage(t, {
    manual: true, onFinalIdentify: async () => { throw Object.assign(new Error(description), { code }) },
  })
  await installSelected(installer)
  assert.equal(installer.state.stage, 'failed')
  assertNoFirmwareWrites(calls)
})

test('the selected package keeps its original hardware ID when mutable cached identity changes', async t => {
  const { installer, reconnects } = await selectedUsbPackage(t)
  installer.state.identity.hardware_id = '112233445566'
  await installSelected(installer)
  assert.equal(installer.state.stage, 'boot_verified')
  assert.equal(reconnects[0].expected.hardwareId, installedIdentity.hardware_id)
})

test('verified startup renews the USB target for another installation after COM renumbering', async t => {
  const { installer, device, calls, directory } = await selectedUsbPackage(t)
  installer.reconnect = async (_original, expected) => {
    assert.equal(expected.hardwareId, installedIdentity.hardware_id)
    device.ports = [{ ...usbDisplay, port: 'COM12', productId: '1002' }]
    device.identity = { ...device.identity, port: 'COM12', firmware_version: '1.1.1' }
    return { ...device.identity }
  }
  await installSelected(installer)
  assert.equal(installer.state.stage, 'boot_verified')
  assert.equal(installer.state.selectedPort, 'COM12')
  await installer.select(directory)
  installer.start('COM12', 'JC4827W543', 460800)
  await installer.completion
  assert.equal(installer.state.stage, 'boot_verified')
  assert.deepEqual(calls.filter(call => call.args.includes('write-flash')).map(call => call.args[call.args.indexOf('--port') + 1]), ['COM8', 'COM12'])
})
