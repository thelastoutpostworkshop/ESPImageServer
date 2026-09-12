import test from 'node:test'
import assert from 'node:assert/strict'
import { mkdtemp, mkdir, writeFile, rm } from 'node:fs/promises'
import path from 'node:path'
import os from 'node:os'
import { FirmwareLibrary } from './firmware-library.mjs'
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
  const f=await fixture(t);await f.library.choose(f.libraryRoot)
  const installer={state:{identity:{port:'COM8',board_target:'OTHER'},selectedPort:'COM8'},select:async()=>{throw new Error('must not select')}}
  await assert.rejects(f.library.select(f.directory,installer),/matching/)
  installer.state.identity.board_target='JC4827W543'
  installer.select=async()=>{installer.state.package={board:'JC4827W543',version:'1.1.5'};installer.selected={}}
  await assert.rejects(f.library.select(f.directory,installer),/changed/)
  assert.equal(installer.selected,null);assert.equal(installer.state.package,null)
  installer.select=async()=>{installer.state.package={board:'JC4827W543',version:'1.1.4'}}
  installer.snapshot=()=>structuredClone(installer.state)
  assert.equal((await f.library.select(f.directory,installer)).package.version,'1.1.4')
})
