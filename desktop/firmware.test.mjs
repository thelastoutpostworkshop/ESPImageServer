import test from 'node:test'
import assert from 'node:assert/strict'
import { mkdtemp, writeFile, readFile, rm, access } from 'node:fs/promises'
import os from 'node:os'
import path from 'node:path'
import { createHash } from 'node:crypto'
import { FirmwareInstaller, parseProbe, validatePackage, writeArguments, runProcess } from './firmware.mjs'

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

test('valid package keeps binary hashes and uses structured arguments without full erase', async t => {
  const f = await fixture(t), pkg = await validatePackage(f.directory)
  const args = writeArguments(pkg.manifest, 'COM8', pkg.segments)
  assert.equal(pkg.segments.length, 4)
  assert.equal(args[args.indexOf('write-flash') + 1], '--flash-mode')
  assert.ok(!args.includes('--erase-all') && !args.includes('--force'))
  assert.deepEqual(args.slice(-2), ['0x10000', 'app.bin'])
})
for (const [name, change, message] of [
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
test('install stages immutable files, verifies four writes, and cleans up', async t => {
  const f = await fixture(t), calls = []
  const installer = new FirmwareInstaller('fake', {
    ports: async () => [{ port: 'COM8' }],
    run: async (_, args, options) => {
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
  installer.start('COM8', 'JC4827W543', 460800)
  assert.throws(() => installer.start('COM8', 'JC4827W543', 460800), /one installation/)
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
test('process runner handles chunked output, errors and timeouts without hardware', async () => {
  const output = await runProcess(process.execPath, ['-e', 'process.stdout.write("one");process.stderr.write("two")'])
  assert.ok(output.includes('one') && output.includes('two'))
  await assert.rejects(runProcess(process.execPath, ['-e', 'process.exit(1)']), /failed/)
  await assert.rejects(runProcess(process.execPath, ['-e', 'setInterval(()=>{},1000)'], { timeout: 100 }), /timed out/)
})
