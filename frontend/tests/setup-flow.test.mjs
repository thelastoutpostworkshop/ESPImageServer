import test from 'node:test'
import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import { compileScript, parse } from '@vue/compiler-sfc'
import { createRenderer, h, nextTick } from 'vue'
const {descriptor}=parse(await readFile(new URL('../src/components/FirmwareInstaller.vue',import.meta.url),'utf8'))
const script=compileScript(descriptor,{id:'setup-flow-test'}).content
  .replace(/from ['"]vue['"]/g,`from ${JSON.stringify(import.meta.resolve('vue'))}`)
  .replace(/import (\w+) from '\.\/\w+\.vue'/g,'const $1 = {}')
  .replace("from '../firmwareStatus.js'",`from ${JSON.stringify(new URL('../src/firmwareStatus.js',import.meta.url).href)}`)
const {default:component}=await import(`data:text/javascript;base64,${Buffer.from(script).toString('base64')}`)
component.render=()=>null
const renderer=createRenderer({createComment:()=>({}),insert(){},remove(){},parentNode:()=>null,nextSibling:()=>null,createElement:()=>({}),createText:()=>({}),setText(){},setElementText(){},patchProp(){}})
const flush=async()=>{await nextTick();await new Promise(r=>setImmediate(r))}
async function mount(t, extraApi = {}) {
  const identity={port:'COM8',board_target:'JC4827W543',hardware_id:'aabbccddeeff',firmware_version:'1.1.3',wifi_configured:true,wifi_connected:true,capabilities:['wifi_scan','wifi_connect','wifi_status','wifi_cancel']}
  const state={selectedPort:'COM8',identity,busy:false,stage:'idle'}
  let installs=0, refreshes=0
  const api={firmwareDownloadState:async()=>({ok:true,value:{busy:false}}),firmwareReleases:async()=>({ok:true,value:{directory:'library',checkedAt:'today',packages:[{board:'JC4827W543',version:'1.1.4',id:'release-package',source:'github'}]}}),
    firmwareState:async()=>({ok:true,value:structuredClone(state)}),firmwarePorts:async()=>({ok:true,value:[{port:'COM8'}]}),
    selectFirmwarePort:async({port})=>{state.selectedPort=port;state.identity=null;return {ok:true,value:structuredClone(state)}},
    refreshFirmwareIdentity:async()=>{refreshes++;state.identity={...identity,wifi_connected:true};return {ok:true,value:structuredClone(state)}},
    installFirmware:async()=>{installs++;return {ok:true,value:structuredClone(state)}}}
  Object.assign(api, extraApi)
  api.checkFirmwareReleases ||= api.firmwareReleases
  globalThis.window={espImageServerDesktop:api,setTimeout:()=>0,clearTimeout(){}}
  const app=renderer.createApp(component);app.mount({})
  t.after(()=>{app.unmount();delete globalThis.window})
  await flush()
  return {form:app._instance.setupState,state,identity,installs:()=>installs,refreshes:()=>refreshes}
}
test('compatible firmware still shows available updates, and Continue skips installation',async t=>{
  const {form,installs}=await mount(t)
  assert.equal(form.panel,'firmware');assert.equal(form.update.kind,'update')
  form.continueSetup();await flush();assert.equal(form.panel,'connection');assert.equal(installs(),0)
  form.manageWifi=true;await flush();assert.equal(form.panel,'wifi')
})
test('saved Wi-Fi is checked automatically while a disconnected board reconnects',async t=>{
  const {form,state,identity,refreshes}=await mount(t)
  state.identity={...identity,wifi_connected:false};form.state=structuredClone(state)
  form.continueSetup();await form.poll();await flush()
  assert.equal(refreshes(),1);assert.equal(form.panel,'connection')
})
test('port changes clear setup progress',async t=>{
  const {form}=await mount(t);form.continueSetup()
  form.port='';await form.selectPort();await flush()
  assert.equal(form.panel,'connect');assert.equal(form.reviewed,false)
})
test('post-flash identification follows the verified new COM port without losing the board',async t=>{
  const {form,state,identity}=await mount(t)
  form.showInstall=true;form.installationStarted=true;state.stage='boot_verified';state.selectedPort='COM9';state.identity={...identity,port:'COM9',firmware_version:'1.1.4'}
  window.espImageServerDesktop.firmwarePorts=async()=>({ok:true,value:[{port:'COM9'}]})
  await form.poll();await flush()
  assert.equal(form.port,'COM9');assert.equal(form.identity.firmware_version,'1.1.4');assert.equal(form.panel,'connection')
})
test('loss of identity requires the next board to pass the firmware step again',async t=>{
  const {form,state,identity}=await mount(t);form.continueSetup()
  state.identity=null;await form.poll();await flush()
  assert.equal(form.reviewed,false);assert.equal(form.panel,'connect')
  state.identity={...identity,hardware_id:'112233445566'};await form.poll();await flush()
  assert.equal(form.panel,'firmware')
})
test('opening firmware management after an earlier install does not auto-close it',async t=>{
  const {form,state}=await mount(t);state.stage='boot_verified';form.showInstall=true
  await form.poll();await flush();assert.equal(form.panel,'install')
})

test('one install action downloads verified GitHub firmware and then starts flashing', async t => {
  let selections = []
  const {form,state,installs} = await mount(t, {
    firmwareReleases: async()=>({ok:true,value:{checkedAt:'today',packages:[{id:'42',source:'github',board:'JC4827W543',version:'1.1.4'}]}}),
    firmwareDownloadState: async()=>({ok:true,value:{busy:false}}),
    selectReleaseFirmware: async request=>{selections.push(request);return {ok:true,value:{...state,package:{board:'JC4827W543',version:'1.1.4',source:'github'}}}}
  })
  assert.equal(form.update.kind,'update'); assert.equal(installs(),0)
  await form.install(); await flush()
  assert.deepEqual(selections,[{id:'42',board:'JC4827W543',port:'COM8'}])
  assert.equal(form.panel,'install'); assert.equal(installs(),1); assert.equal(form.installationStarted,true)
})

test('GitHub and download failures do not start flashing', async t => {
  const {form,installs} = await mount(t, {
    firmwareReleases: async()=>({ok:true,value:{checkedAt:null,error:'GitHub unavailable',packages:[]}}),
    firmwareDownloadState: async()=>({ok:true,value:{busy:false}}),
    selectReleaseFirmware: async()=>({ok:false,error:'Checksum failed'})
  })
  assert.equal(form.update.kind,'unknown')
  form.library={checkedAt:'today',packages:[{id:'42',source:'github',board:'JC4827W543',version:'1.1.4'}]}
  await form.install(); await flush()
  assert.equal(form.error,'Checksum failed'); assert.equal(installs(),0)
})


test('downloaded board/version mismatch prevents flashing', async t => {
  const {form,installs} = await mount(t, {
    selectReleaseFirmware:async()=>({ok:true,value:{package:{board:'ESP32_C6_LCD_147',version:'1.1.4',source:'github'}}})
  })
  await form.install()
  assert.match(form.error, /does not match/)
  assert.equal(installs(),0)
})

test('repeated install clicks cannot duplicate a download and cancellation never flashes', async t => {
  let finishDownload, downloads = 0
  const {form,installs} = await mount(t, {
    selectReleaseFirmware: async()=>{ downloads++; return new Promise(resolve=>{finishDownload=resolve}) }
  })
  const first = form.install()
  await flush()
  await form.install()
  assert.equal(downloads, 1)
  assert.equal(form.canInstall, false)
  finishDownload({ok:false,error:'Download cancelled'})
  await first
  assert.equal(installs(), 0)
  assert.equal(form.error, 'Download cancelled')
  assert.equal(form.pending, false)
})

test('unidentified display can continue to firmware, but not Wi-Fi or Ready', async t => {
  const {form,state,installs} = await mount(t)
  state.identity = null
  state.identityError = 'No response'
  form.state = structuredClone(state)
  await flush()
  assert.equal(form.step, 1)
  form.goToStep(2)
  assert.equal(form.panel, 'install')
  assert.equal(form.step, 2)
  assert.equal(form.identity, null)
  form.goToStep(3)
  form.goToStep(4)
  assert.equal(form.panel, 'install')
  await form.install()
  assert.equal(installs(), 0)
  form.goToStep(1)
  assert.equal(form.panel, 'connect')
})

test('stepper navigation requires a port and remains locked during installation', async t => {
  const {form} = await mount(t)
  form.port = ''; await form.selectPort(); await flush()
  form.goToStep(2)
  assert.equal(form.step, 1)
  form.port = 'COM8'; form.goToStep(2)
  form.state = {...form.state, busy:true}
  form.goToStep(1)
  assert.equal(form.step, 2)
})

test('identified display can revisit each permitted step', async t => {
  const {form} = await mount(t)
  form.goToStep(1); assert.equal(form.panel, 'connect')
  form.goToStep(2); assert.equal(form.panel, 'firmware')
  form.goToStep(3); assert.equal(form.panel, 'wifi')
  form.goToStep(4); assert.equal(form.panel, 'connection')
})
