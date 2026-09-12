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
async function mount(t) {
  const identity={port:'COM8',board_target:'JC4827W543',hardware_id:'aabbccddeeff',firmware_version:'1.1.3',wifi_configured:true,wifi_connected:true,capabilities:['wifi_scan','wifi_connect','wifi_status','wifi_cancel']}
  const state={selectedPort:'COM8',identity,busy:false,stage:'idle'}
  let installs=0, refreshes=0
  const api={firmwareLibrary:async()=>({ok:true,value:{directory:'library',checkedAt:'today',packages:[{board:'JC4827W543',version:'1.1.4',directory:'library/package'}]}}),
    firmwareState:async()=>({ok:true,value:structuredClone(state)}),firmwarePorts:async()=>({ok:true,value:[{port:'COM8'}]}),
    selectFirmwarePort:async({port})=>{state.selectedPort=port;state.identity=null;return {ok:true,value:structuredClone(state)}},
    refreshFirmwareIdentity:async()=>{refreshes++;state.identity={...identity,wifi_connected:true};return {ok:true,value:structuredClone(state)}},
    installFirmware:async()=>{installs++;return {ok:true,value:structuredClone(state)}}}
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
test('port changes clear setup progress and installation confirmation',async t=>{
  const {form}=await mount(t);form.continueSetup();form.confirmed=true
  form.port='';await form.selectPort();await flush()
  assert.equal(form.panel,'connect');assert.equal(form.confirmed,false);assert.equal(form.reviewed,false)
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
