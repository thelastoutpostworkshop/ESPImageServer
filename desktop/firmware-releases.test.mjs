import test from 'node:test'
import assert from 'node:assert/strict'
import { createHash } from 'node:crypto'
import { mkdtemp, readdir, readFile, rm } from 'node:fs/promises'
import os from 'node:os'
import path from 'node:path'
import { FirmwareReleases, REPOSITORY, releasePackages, downloadBytes, extractFirmwareZip } from './firmware-releases.mjs'
import { FirmwareInstaller } from './firmware.mjs'

const hash = data => createHash('sha256').update(data).digest('hex')
const base = `https://github.com/${REPOSITORY}/releases/download/v1.1.5/`
const filename = 'ESPImageDisplay-CHEAP_YELLOW_DISPLAY-1.1.5.zip'

// Minimal stored ZIP fixture encoder, including CRC and the central directory.
function zip(entries) {
  const local = [], central = []; let offset = 0
  for (const [name, input, mode = 0x8000] of entries) {
    const data = Buffer.from(input), label = Buffer.from(name)
    let crc = 0xffffffff
    for (const byte of data) { crc ^= byte; for (let bit = 0; bit < 8; bit++) crc = (crc >>> 1) ^ (0xedb88320 & -(crc & 1)) }
    crc = (crc ^ 0xffffffff) >>> 0
    const header = Buffer.alloc(30); header.writeUInt32LE(0x04034b50); header.writeUInt16LE(20, 4)
    header.writeUInt32LE(crc,14); header.writeUInt32LE(data.length,18); header.writeUInt32LE(data.length,22); header.writeUInt16LE(label.length,26)
    local.push(header,label,data)
    const record = Buffer.alloc(46); record.writeUInt32LE(0x02014b50); record.writeUInt16LE(0x314,4); record.writeUInt16LE(20,6)
    record.writeUInt32LE(crc,16); record.writeUInt32LE(data.length,20); record.writeUInt32LE(data.length,24); record.writeUInt16LE(label.length,28)
    record.writeUInt32LE((mode << 16) >>> 0,38); record.writeUInt32LE(offset,42)
    central.push(record,label); offset += header.length + label.length + data.length
  }
  const directory = Buffer.concat(central), end = Buffer.alloc(22); end.writeUInt32LE(0x06054b50)
  end.writeUInt16LE(entries.length,8); end.writeUInt16LE(entries.length,10); end.writeUInt32LE(directory.length,12); end.writeUInt32LE(offset,16)
  return Buffer.concat([...local,directory,end])
}

function fixture() {
  const image = Buffer.alloc(256); image[0] = 0xe9
  const table = Buffer.alloc(32); table.writeUInt16LE(0x50aa); table.writeUInt32LE(0x10000,4); table.writeUInt32LE(0x100000,8)
  const inputs = [['bootloader',0x1000,image],['partition_table',0x8000,table],['ota_data',0xe000,Buffer.alloc(8192)],['application',0x10000,image]]
  const manifest = {schema_version:1,package_type:'esp-image-display-firmware',installation_type:'first_install',
    board_target:'CHEAP_YELLOW_DISPLAY',firmware_version:'1.1.5',chip:'esp32',flash:{mode:'dio',frequency:'80m',size_bytes:4194304},
    segments:inputs.map(([role,offset,data])=>({role,offset:`0x${offset.toString(16)}`,file:`${role}.bin`,size_bytes:data.length,sha256:hash(data)}))}
  const entries = [...inputs.map(([role,,data])=>[`${role}.bin`,data]), ['manifest.json',JSON.stringify(manifest)],['LICENSE.txt','Test license']]
  const data = zip(entries), digest = hash(data)
  const release = { tag_name:'v1.1.5',draft:false,prerelease:false,body:'Test release',assets:[
    {id:1,name:filename,state:'uploaded',size:data.length,digest:`sha256:${digest}`,browser_download_url:base+filename},
    {id:2,name:'SHA256SUMS.txt',state:'uploaded',size:150,browser_download_url:base+'SHA256SUMS.txt'}]}
  return {manifest,entries,data,digest,release}
}
async function temp(t) {
  const root = await mkdtemp(path.join(os.tmpdir(),'firmware-releases-test-'))
  t.after(async()=> {
    assert.equal(path.dirname(path.resolve(root)),path.resolve(os.tmpdir()))
    assert.ok(path.basename(root).startsWith('firmware-releases-test-'))
    await rm(root,{recursive:true,force:true})
  })
  return root
}
async function setup(t, overrides = {}) {
  const root = await temp(t), f = fixture(), calls = []
  const download = async (url,limit,options) => {
    calls.push(url)
    if (overrides.download) return overrides.download(url,limit,options,f)
    if (url.includes('api.github.com')) return Buffer.from(JSON.stringify([f.release]))
    if (url.endsWith('SHA256SUMS.txt')) return Buffer.from(`${f.digest}  ${filename}\n`)
    return f.data
  }
  const service = new FirmwareReleases(root,{download})
  const installer = new FirmwareInstaller('unused')
  installer.knownPorts = [{ port: 'COM3' }, { port: 'COM4' }]
  installer.selectPort('COM3')
  const request = {id:'1',board:'CHEAP_YELLOW_DISPLAY',port:'COM3'}
  await service.check()
  return {root,f,calls,service,installer,request}
}

test('catalog excludes drafts, wrong repository URLs and incomplete releases; preserves preview label',()=> {
  const {release:r} = fixture()
  assert.equal(releasePackages([r])[0].board,'CHEAP_YELLOW_DISPLAY')
  assert.equal(releasePackages([{...r,prerelease:true}])[0].prerelease,true)
  assert.deepEqual(releasePackages([{...r,draft:true}]),[])
  assert.deepEqual(releasePackages([{...r,assets:r.assets.slice(0,1)}]),[])
  assert.deepEqual(releasePackages([{...r,assets:r.assets.map(a=>({...a,browser_download_url:a.browser_download_url.replace(REPOSITORY,'attacker/repo')}))}]),[])
})
for (const port of ['COM3', '/dev/ttyACM0', '/dev/cu.usbmodem1101']) test(`${port}: download validates real package, caches verified ZIP and never starts flashing`,async t=> {
  const {service,installer,request,calls,root,f} = await setup(t)
  installer.knownPorts = [{ port }]
  installer.selectPort(port)
  request.port = port
  const state = await service.select(request,installer)
  assert.equal(state.package.version,'1.1.5'); assert.equal(state.busy,false); assert.equal(state.stage,'ready')
  assert.equal(installer.completion,undefined)
  assert.equal(hash(await readFile(path.join(root,f.digest+'.zip'))),f.digest)
  await service.select(request,installer)
  assert.equal(calls.filter(url=>url.endsWith(filename)).length,1)
})
test('checksum mismatch cannot select firmware and leaves no unpacked package',async t=> {
  const {service,installer,request,root} = await setup(t,{download:async(url,limit,options,f)=>
    url.includes('api.github.com') ? Buffer.from(JSON.stringify([f.release])) : url.endsWith('SHA256SUMS.txt') ?
      Buffer.from(`${f.digest}  ${filename}\n`) : Buffer.alloc(f.data.length)})
  await assert.rejects(service.select(request,installer),/checksum failed/)
  assert.equal(installer.selected,undefined); assert.equal(service.state.busy,false)
  assert.deepEqual(await readdir(root),[])
})
test('catalog board/version must match the downloaded manifest',async t=> {
  const {service,installer,request,f,root} = await setup(t)
  service.state.packages[0].version = '1.1.6'
  await assert.rejects(service.select(request,installer),/does not match/)
  assert.equal(installer.selected,undefined)
  assert.deepEqual(await readdir(root),[])
})
test('board change during download prevents selection',async t=> {
  const s = await setup(t)
  const original = s.service.download
  s.service.download = async(...args)=>{const data=await original(...args); if(args[0].endsWith(filename))s.installer.selectPort('COM4'); return data}
  await assert.rejects(s.service.select(s.request,s.installer),/USB display changed/)
  assert.equal(s.installer.selected,undefined)
})
test('preview firmware requires explicit opt in and a matching physical board',async t=> {
  const {service,installer,request} = await setup(t)
  service.state.packages[0].prerelease = true
  await assert.rejects(service.select(request,installer),/matching firmware release/)
  await assert.rejects(service.select({...request,board:'JC4827W543',allowPrerelease:true},installer),/matching firmware release/)
  await service.select({...request,allowPrerelease:true},installer)
})
test('cancellation resets busy state without selecting or flashing',async t=> {
  const s = await setup(t)
  s.service.download = async(url,limit,{signal})=> new Promise((resolve,reject)=>signal.addEventListener('abort',()=>reject(new Error('aborted')),{once:true}))
  const pending = s.service.select(s.request,s.installer)
  s.service.cancel()
  await assert.rejects(pending,/Download cancelled/)
  assert.equal(s.service.state.busy,false); assert.equal(s.installer.selected,undefined)
})
test('failed catalog refresh cannot claim current firmware',async t=> {
  const {service} = await setup(t)
  service.download = async()=>{throw new Error('offline')}
  const result = await service.check(true)
  assert.equal(result.checkedAt,null); assert.deepEqual(result.packages,[]); assert.match(result.error,/offline/)
})
test('ZIP traversal, duplicate files, symlinks and oversized expansion are rejected',async t=> {
  for (const entries of [[['../escape.bin','x']],[['a.bin','x'],['a.bin','y']],[['a.bin','target',0xa000]], [['manifest.json',Buffer.alloc(65537)]]]) {
    await assert.rejects(extractFirmwareZip(zip(entries),await temp(t)))
  }
})
test('download rejects an untrusted redirect without requesting its destination',async()=> {
  let calls=0
  await assert.rejects(downloadBytes(base+filename,100,{fetcher:async()=>{calls++;return new Response(null,{status:302,headers:{location:'http://127.0.0.1/private'}})}}),/outside GitHub/)
  assert.equal(calls,1)
})
test('download bounds bytes without content-length and explains GitHub rate limits',async()=> {
  await assert.rejects(downloadBytes(base+filename,3,{fetcher:async()=>new Response('1234')}),/size limit/)
  await assert.rejects(downloadBytes(base+filename,3,{fetcher:async()=>new Response('',{status:403})}),/limiting requests/)
})
