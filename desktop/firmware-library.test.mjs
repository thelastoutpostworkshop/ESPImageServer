import test from 'node:test'
import assert from 'node:assert/strict'
import { mkdtemp, mkdir, writeFile, rm } from 'node:fs/promises'
import path from 'node:path'
import os from 'node:os'
import { createHash } from 'node:crypto'
import { FirmwareLibrary } from './firmware-library.mjs'
import { FirmwareInstaller, validatePackage } from './firmware.mjs'
async function fixture(t) {
  const root = await mkdtemp(path.join(os.tmpdir(), 'esp-library-'))
  t.after(() => rm(root,{recursive:true,force:true}))
  const libraryRoot = path.join(root,'firmware')
  const directory = path.join(libraryRoot,'JC4827W543','1.1.4')
  await mkdir(directory,{recursive:true}); await writeFile(path.join(directory,'manifest.json'),'{}')
  const validate = async folder => ({directory:folder,manifest:{board_target:'JC4827W543',firmware_version:'1.1.4',release_notes:'Forget Wi-Fi support'}})
  const settings = path.join(root,'settings.json')
  return {root, libraryRoot, directory, settings, validate, library:new FirmwareLibrary(settings,validate)}
}
test('library remembers the chosen root and checks board/version folders', async t => {
  const f=await fixture(t), result=await f.library.choose(f.libraryRoot)
  assert.equal(result.packages.length,1); assert.equal(result.packages[0].notes,'Forget Wi-Fi support')
  assert.ok(result.checkedAt)
  assert.equal((await new FirmwareLibrary(f.settings,f.validate).load()).packages.length,1)
})
test('invalid packages and unavailable libraries cannot appear as checked updates', async t => {
  const f=await fixture(t)
  f.library.validate=async()=>{throw new Error('Checksum mismatch')}
  const result=await f.library.choose(f.libraryRoot)
  assert.equal(result.packages.length,0); assert.match(result.issues[0].message,/Checksum/)
  await rm(f.libraryRoot,{recursive:true,force:true})
  const missing=await f.library.scan()
  assert.equal(missing.checkedAt,null); assert.match(missing.error,/Could not check/)
})
test('reviewing a library update binds the board and revalidates its version', async t => {
  const f=await fixture(t)
  const { packages }=await f.library.choose(f.libraryRoot)
  // The UI submits the scanned path, which realpath may canonicalize on Windows.
  const directory=packages[0].directory
  const installer={state:{identity:{port:'COM8',board_target:'OTHER'},selectedPort:'COM8'},select:async()=>{throw new Error('must not select')},
    captureInstallTarget(port,board) { return {port,board,identity:{...this.state.identity},mode:'identified'} }}
  await assert.rejects(f.library.select(directory,installer),/matching/)
  installer.state.identity.board_target='JC4827W543'
  installer.select=async()=>{installer.state.package={board:'JC4827W543',version:'1.1.5'};installer.selected={}}
  await assert.rejects(f.library.select(directory,installer),/changed/)
  assert.equal(installer.selected,null);assert.equal(installer.state.package,null)
  installer.select=async()=>{installer.state.package={board:'JC4827W543',version:'1.1.4'}}
  installer.snapshot=()=>structuredClone(installer.state)
  assert.equal((await f.library.select(directory,installer)).package.version,'1.1.4')
})

test('library selection retains the original USB identity through asynchronous validation', async t => {
  const f = await fixture(t)
  const image = Buffer.alloc(128); image[0] = 0xe9; image.writeUInt16LE(9, 12)
  const table = Buffer.alloc(32); table.writeUInt16LE(0x50aa)
  table.writeUInt32LE(0x10000, 4); table.writeUInt32LE(0x100000, 8)
  const definitions = [
    ['bootloader', '0x0', image], ['partition_table', '0x8000', table],
    ['ota_data', '0xe000', Buffer.alloc(8192)], ['application', '0x10000', image]
  ]
  const manifest = { schema_version: 1, package_type: 'esp-image-display-firmware', installation_type: 'first_install',
    board_target: 'JC4827W543', firmware_version: '1.1.4', chip: 'esp32s3',
    flash: { mode: 'dio', frequency: '80m', size_bytes: 4194304 }, segments: [] }
  for (const [role, offset, data] of definitions) {
    const file = `${role}.bin`
    await writeFile(path.join(f.directory, file), data)
    manifest.segments.push({ role, offset, file, size_bytes: data.length, sha256: createHash('sha256').update(data).digest('hex') })
  }
  await writeFile(path.join(f.directory, 'manifest.json'), JSON.stringify(manifest))
  f.library.validate = validatePackage
  const { packages } = await f.library.choose(f.libraryRoot)
  const original = { port: 'COM8', board_target: 'JC4827W543', hardware_id: 'aabbccddeeff' }
  let physical = original
  const commands = []
  const installer = new FirmwareInstaller('unused', {
    ports: async () => [{ port: original.port }],
    identify: async () => ({ ...physical }),
    run: async (_, args) => {
      commands.push(args)
      return args.includes('flash-id') ? 'Chip type: ESP32-S3\nDetected flash size: 4MB\n' : 'Hash of data verified.\n'.repeat(4)
    }
  })
  await installer.identifyFirmware(original.port)
  const select = installer.select.bind(installer)
  installer.select = async (...args) => {
    installer.state.identity = null
    physical = { ...original, hardware_id: '112233445566' }
    return select(...args)
  }
  await f.library.select(packages[0].directory, installer)
  installer.start(original.port, original.board_target, 115200)
  await installer.completion
  assert.equal(installer.state.stage, 'failed')
  assert.match(installer.state.error, /changed|match|original/i)
  assert.equal(commands.filter(args => args.includes('write-flash')).length, 0)
})
