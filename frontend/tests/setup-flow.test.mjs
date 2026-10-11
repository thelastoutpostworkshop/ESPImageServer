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
async function mount(t, extraApi = {}, initialState = {}) {
  const identity={port:'COM8',board_target:'JC4827W543',hardware_id:'aabbccddeeff',firmware_version:'1.1.3',wifi_configured:true,wifi_connected:true,capabilities:['wifi_scan','wifi_connect','wifi_status','wifi_cancel']}
  const state={selectedPort:'COM8',identity,busy:false,stage:'idle',...initialState}
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

test('installation progress distinguishes download, upload, verification, and startup', async t => {
  const {form} = await mount(t)
  form.showInstall = true
  form.pending = true
  assert.equal(form.installationActive, true)
  assert.equal(form.installationProgress.label, 'Preparing firmware installation')
  form.download = {busy:true,download:{stage:'downloading',received:25,total:100}}
  assert.equal(form.installationProgress.percent, 25)
  form.download.download.stage = 'validating'
  assert.equal(form.installationProgress.percent, null)
  assert.equal(form.installationProgress.label, 'Checking downloaded firmware')
  form.download = {busy:false}
  form.pending = false
  form.state = {...form.state,busy:true,stage:'checking_identity',progress:null}
  assert.equal(form.installationProgress.label, 'Checking the connected display')
  assert.equal(form.installationProgress.percent, null)
  assert.match(form.installationProgress.detail, /before writing firmware/)
  form.state = {...form.state,busy:true,stage:'writing_and_verifying',progress:{percent:62.9,verified:3,total:4,phase:'writing'}}
  assert.equal(form.installationProgress.percent, 62)
  assert.equal(form.installationProgress.detail, '3 of 4 firmware files verified.')
  form.state.progress.phase = 'verifying'
  assert.equal(form.installationProgress.label, 'Verifying firmware on your display')
  form.state.stage = 'identifying'
  assert.equal(form.installationProgress.percent, null)
  assert.equal(form.installationProgress.label, 'Checking firmware startup')
  form.state.stage = 'failed'; form.state.busy = false
  assert.equal(form.installationActive, false)
})

test('the confirmed board portrait remains available on every permitted setup step', async t => {
  const {form} = await mount(t)
  const image = '/ui/board-catalog/JC4827W543.png'
  assert.equal(form.detectedBoard.image, image)
  for (const step of [1, 2, 3, 4, 2]) {
    form.goToStep(step)
    await flush()
    assert.equal(form.step, step)
    assert.equal(form.detectedBoard.image, image)
  }
})

test('an uploading board keeps its portrait without treating cached identification as live USB identity', async t => {
  const {form,state} = await mount(t)
  form.showInstall = true
  state.identity = null
  state.busy = true
  state.stage = 'writing_and_verifying'
  await form.poll(); await flush()

  assert.equal(form.detectedBoard.value, 'JC4827W543')
  assert.equal(form.identity, null)
  assert.equal(form.compatible, false)
  assert.equal(form.canInstall, false)
  assert.equal(form.step, 2)
  form.goToStep(3)
  form.goToStep(4)
  assert.equal(form.step, 2)

  for (const stage of ['written', 'failed']) {
    state.busy = false
    state.stage = stage
    await form.poll(); await flush()
    assert.equal(form.detectedBoard.value, 'JC4827W543')
    assert.equal(form.identity, null)
    assert.equal(form.compatible, false)
    form.goToStep(3)
    form.goToStep(4)
    assert.equal(form.step, 2)
  }
})

test('selecting another USB port clears the previous board portrait', async t => {
  const {form} = await mount(t)
  assert.equal(form.detectedBoard.value, 'JC4827W543')
  form.port = 'COM9'
  await form.selectPort(); await flush()
  assert.equal(form.detectedBoard, null)
  assert.equal(form.confirmedBoard, null)
  assert.equal(form.identity, null)
})

test('a disconnected USB port clears the board portrait and setup progress', async t => {
  const {form} = await mount(t)
  form.continueSetup()
  window.espImageServerDesktop.firmwarePorts = async()=>({ok:true,value:[]})
  await form.checkPorts(); await flush()
  assert.equal(form.port, '')
  assert.equal(form.detectedBoard, null)
  assert.equal(form.confirmedBoard, null)
  assert.equal(form.identifiedBoard, null)
  assert.equal(form.needsBoardChoice, true)
  assert.equal(form.installBoard, '')
  assert.equal(form.reviewed, false)
})

test('replacement hardware resets setup and replaces the portrait with the new board model', async t => {
  const {form,state,identity} = await mount(t)
  form.continueSetup()
  state.identity = {...identity,hardware_id:'112233445566',board_target:'ESP32_C6_LCD_147'}
  await form.poll(); await flush()
  assert.equal(form.reviewed, false)
  assert.equal(form.panel, 'firmware')
  assert.equal(form.detectedBoard.value, 'ESP32_C6_LCD_147')
  assert.equal(form.detectedBoard.image, '/ui/board-catalog/ESP32_C6_LCD_147.png')
  assert.equal(form.identifiedBoard.value, 'ESP32_C6_LCD_147')
  assert.equal(form.installBoard, 'ESP32_C6_LCD_147')
  assert.equal(form.needsBoardChoice, false)
  state.identity = null
  await form.poll(); await flush()
  assert.equal(form.installBoard, 'ESP32_C6_LCD_147')
  assert.equal(form.needsBoardChoice, false)
})

test('verified startup on a new COM port retains the correctly identified portrait', async t => {
  const {form,state,identity} = await mount(t)
  form.showInstall = true
  form.installationStarted = true
  state.stage = 'boot_verified'
  state.selectedPort = 'COM9'
  state.identity = {...identity,port:'COM9',firmware_version:'1.1.4'}
  window.espImageServerDesktop.firmwarePorts = async()=>({ok:true,value:[{port:'COM9'}]})
  await form.poll(); await flush()
  assert.equal(form.port, 'COM9')
  assert.equal(form.confirmedBoard.port, 'COM9')
  assert.equal(form.detectedBoard.value, 'JC4827W543')
  assert.equal(form.panel, 'connection')
})

test('reopening setup during an active upload restores only the package portrait for that USB port', async t => {
  const {form} = await mount(t, {}, {
    port:'COM8',identity:null,busy:true,stage:'writing_and_verifying',
    package:{board:'CHEAP_YELLOW_DISPLAY',version:'1.1.41',source:'github'}
  })
  assert.equal(form.detectedBoard.value, 'CHEAP_YELLOW_DISPLAY')
  assert.equal(form.detectedBoard.image, '/ui/board-catalog/CHEAP_YELLOW_DISPLAY.png')
  assert.equal(form.identity, null)
  assert.equal(form.compatible, false)
  assert.equal(form.panel, 'install')
})

test('a package belonging to another USB port cannot restore a stale board portrait', async t => {
  const {form} = await mount(t, {}, {
    selectedPort:'COM8',port:'COM7',identity:null,busy:true,stage:'writing_and_verifying',
    package:{board:'CHEAP_YELLOW_DISPLAY',version:'1.1.41',source:'github'}
  })
  assert.equal(form.detectedBoard, null)
  assert.equal(form.confirmedBoard, null)
  assert.equal(form.identity, null)
})

test('installing a manually selected model keeps its portrait without granting unidentified firmware Wi-Fi access', async t => {
  const {form,state,installs} = await mount(t, {
    firmwareReleases:async()=>({ok:true,value:{checkedAt:'today',packages:[{id:'cyd',source:'github',board:'CHEAP_YELLOW_DISPLAY',version:'1.1.41'}]}}),
    selectReleaseFirmware:async()=>({ok:true,value:{...state,package:{source:'github',board:'CHEAP_YELLOW_DISPLAY',version:'1.1.41'}}})
  }, {identity:null})
  form.goToStep(2)
  form.board = 'CHEAP_YELLOW_DISPLAY'
  await flush()
  assert.equal(form.canInstall, true)
  await form.install(); await flush()
  assert.equal(installs(), 1)
  assert.equal(form.detectedBoard.value, 'CHEAP_YELLOW_DISPLAY')
  assert.equal(form.identity, null)
  assert.equal(form.compatible, false)
  form.goToStep(3)
  assert.equal(form.step, 2)
})

test('reported replacement or disconnected hardware removes a cached portrait when no USB identity is available', async t => {
  const {form,state,identity} = await mount(t)
  state.identity = null
  state.identityError = 'The USB display disconnected'
  await form.poll(); await flush()
  assert.equal(form.detectedBoard, null)
  assert.equal(form.confirmedBoard, null)
  assert.equal(form.identifiedBoard, null)
  assert.equal(form.needsBoardChoice, true)
  assert.equal(form.installBoard, '')
  assert.equal(form.canInstall, false)

  state.identity = {...identity,board_target:'ESP32_C6_LCD_147'}
  state.identityError = ''
  await form.poll(); await flush()
  assert.equal(form.detectedBoard.value, 'ESP32_C6_LCD_147')
  state.identity = null
  state.identityError = 'The display hardware changed'
  await form.poll(); await flush()
  assert.equal(form.detectedBoard, null)
  assert.equal(form.confirmedBoard, null)
  assert.equal(form.identifiedBoard, null)
  assert.equal(form.needsBoardChoice, true)
  assert.equal(form.installBoard, '')
  assert.equal(form.canInstall, false)
})

test('a new installation failure opens recovery and log panels without overriding a later manual collapse', async t => {
  const {form,state} = await mount(t)
  form.supportPanels = ['device']
  state.stage = 'failed'
  state.error = 'Write failed'
  state.log = 'Could not write firmware'
  await form.poll(); await flush()
  assert.ok(form.supportPanels.includes('device'))
  assert.ok(form.supportPanels.includes('recovery'))
  assert.ok(form.supportPanels.includes('log'))

  form.supportPanels = []
  await form.poll(); await flush()
  assert.deepEqual(form.supportPanels, [])

  state.stage = 'connecting'
  await form.poll(); await flush()
  state.stage = 'failed'
  await form.poll(); await flush()
  assert.ok(form.supportPanels.includes('recovery'))
  assert.ok(form.supportPanels.includes('log'))
})

test('identity errors open recovery once per new error and respect a manually closed panel while polling', async t => {
  const {form,state} = await mount(t)
  state.identityError = 'No USB identity received'
  await form.poll(); await flush()
  assert.ok(form.supportPanels.includes('recovery'))

  form.supportPanels = []
  await form.poll(); await flush()
  assert.deepEqual(form.supportPanels, [])

  state.identityError = 'USB identity did not match this display'
  await form.poll(); await flush()
  assert.ok(form.supportPanels.includes('recovery'))
})

test('every supported board offers conditional BOOT and RESET guidance while connecting', async t => {
  const {form} = await mount(t)
  form.showInstall = true
  for (const board of [...form.boardItems.map(item => item.value), undefined]) {
    form.state = {...form.state,identity:null,busy:true,stage:'connecting',package:board ? {board} : null}
    await flush()
    assert.equal(form.installationProgress.label, 'Connecting to your display')
    assert.equal(form.installationProgress.percent, null)
    assert.match(form.installationProgress.detail, /If connection takes too long, hold BOOT, press and release RESET\/EN, then release BOOT\./)
    if (board === 'CHEAP_YELLOW_DISPLAY') assert.match(form.installationProgress.detail, /keeps the board in download mode/)
    else assert.doesNotMatch(form.installationProgress.detail, /keeps the board in download mode/)
    assert.equal(form.installationActive, true)
    assert.equal(form.locked, true)
    assert.equal(form.identity, null)
    assert.equal(form.compatible, false)
    assert.equal(form.canInstall, false)
    form.goToStep(1)
    form.goToStep(3)
    assert.equal(form.step, 2)
  }
})

test('BOOT and RESET connection hints disappear during transfer, verification, restart, and startup checks', async t => {
  const {form} = await mount(t)
  form.showInstall = true
  const stages = [
    {stage:'checking_identity',label:'Checking the connected display',percent:null},
    {stage:'writing_and_verifying',phase:'writing',label:'Writing firmware to your display',percent:62},
    {stage:'writing_and_verifying',phase:'verifying',label:'Verifying firmware on your display',percent:62},
    {stage:'restarting',label:'Restarting your display',percent:null},
    {stage:'identifying',label:'Checking firmware startup',percent:null}
  ]
  for (const {value:board} of form.boardItems) {
    for (const {stage,phase,label,percent} of stages) {
      form.state = {...form.state,identity:null,busy:true,stage,package:{board},
        progress:phase ? {phase,percent:62.9,verified:2,total:4} : null}
      await flush()
      assert.equal(form.installationProgress.label, label)
      assert.equal(form.installationProgress.percent, percent)
      assert.doesNotMatch(form.installationProgress.detail, /\bBOOT\b|\bRESET\/EN\b/)
      if (phase) assert.equal(form.installationProgress.detail, '2 of 4 firmware files verified.')
      assert.equal(form.installationActive, true)
      assert.equal(form.locked, true)
      form.goToStep(1)
      assert.equal(form.step, 2)
    }
  }
})

test('the physical-model picker is rendered only when a model choice is still needed', () => {
  const picker = descriptor.template.content.match(/<fieldset\b[^>]*\bclass="[^"]*\bboard-picker\b[^"]*"[^>]*>/)?.[0]
  assert.ok(picker, 'the firmware step contains a physical-model picker')
  assert.equal(picker.match(/\bv-if="([^"]+)"/)?.[1], 'needsBoardChoice')
})

test('an identified display keeps the model picker hidden through a wrong-boot failure and retries that exact target', async t => {
  const known = {
    port:'COM8',board_target:'CHEAP_YELLOW_DISPLAY',hardware_id:'08a6f7238e98',firmware_version:'1.1.41',
    wifi_configured:true,wifi_connected:true,capabilities:['wifi_scan','wifi_connect','wifi_status','wifi_cancel']
  }
  const packages = [
    {id:'cyd',source:'github',board:'CHEAP_YELLOW_DISPLAY',version:'1.1.42'},
    {id:'jc',source:'github',board:'JC4827W543',version:'1.1.42'}
  ]
  const requests = []
  const {form,state} = await mount(t, {
    firmwareReleases:async()=>({ok:true,value:{checkedAt:'today',packages}}),
    selectReleaseFirmware:async request=>{
      requests.push(['package',request])
      state.identity = null
      state.package = packages.find(pkg => pkg.id === request.id)
      return {ok:true,value:structuredClone(state)}
    },
    installFirmware:async request=>{
      requests.push(['install',request])
      state.busy = true
      state.stage = 'connecting'
      return {ok:true,value:structuredClone(state)}
    }
  }, {identity:known})
  assert.equal(form.needsBoardChoice, false)
  assert.equal(form.identifiedBoard.value, 'CHEAP_YELLOW_DISPLAY')
  await form.install(); await flush()
  assert.equal(form.identity, null)
  assert.equal(form.needsBoardChoice, false)
  assert.equal(form.confirmedBoard.identified, true)
  assert.equal(form.canInstall, false)

  state.busy = false
  state.stage = 'failed'
  state.error = 'Wrong boot mode detected (0x13)! The chip needs to be in download mode.'
  await form.poll(); await flush()
  assert.equal(form.panel, 'install')
  assert.equal(form.needsBoardChoice, false)
  assert.equal(form.identifiedBoard.value, 'CHEAP_YELLOW_DISPLAY')
  assert.equal(form.compatible, false)
  form.goToStep(3)
  form.goToStep(4)
  assert.equal(form.step, 2)

  // A stale manual selection must not override the model identified over USB.
  form.board = 'JC4827W543'
  assert.equal(form.installBoard, 'CHEAP_YELLOW_DISPLAY')
  assert.equal(form.update.latest.board, 'CHEAP_YELLOW_DISPLAY')
  assert.equal(form.canInstall, true)
  await form.install(); await flush()
  assert.equal(form.confirmedBoard.identified, true)
  assert.equal(form.needsBoardChoice, false)
  assert.deepEqual(requests, [
    ['package',{id:'cyd',board:'CHEAP_YELLOW_DISPLAY',port:'COM8'}],
    ['install',{port:'COM8',board:'CHEAP_YELLOW_DISPLAY',baud:460800}],
    ['package',{id:'cyd',board:'CHEAP_YELLOW_DISPLAY',port:'COM8'}],
    ['install',{port:'COM8',board:'CHEAP_YELLOW_DISPLAY',baud:460800}]
  ])
})

test('a failed manual installation keeps the model picker available and allows a different model selection', async t => {
  const packages = [
    {id:'cyd',source:'github',board:'CHEAP_YELLOW_DISPLAY',version:'1.1.42'},
    {id:'c6',source:'github',board:'ESP32_C6_LCD_147',version:'1.1.42'}
  ]
  const requests = []
  const {form,state} = await mount(t, {
    firmwareReleases:async()=>({ok:true,value:{checkedAt:'today',packages}}),
    selectReleaseFirmware:async request=>{
      state.package = packages.find(pkg => pkg.id === request.id)
      return {ok:true,value:structuredClone(state)}
    },
    installFirmware:async request=>{
      requests.push(request)
      state.busy = false
      state.stage = 'failed'
      state.error = 'The board needs to be in download mode.'
      return {ok:true,value:structuredClone(state)}
    }
  }, {identity:null})
  form.goToStep(2)
  form.board = 'CHEAP_YELLOW_DISPLAY'
  await flush()
  assert.equal(form.needsBoardChoice, true)
  await form.install(); await flush()
  assert.equal(form.detectedBoard.value, 'CHEAP_YELLOW_DISPLAY')
  assert.equal(form.identifiedBoard, null)
  assert.equal(form.confirmedBoard.identified, false)
  assert.equal(form.needsBoardChoice, true)
  assert.equal(form.compatible, false)

  form.board = 'ESP32_C6_LCD_147'
  assert.equal(form.installBoard, 'ESP32_C6_LCD_147')
  assert.equal(form.update.latest.board, 'ESP32_C6_LCD_147')
  assert.equal(form.canInstall, true)
  await form.install(); await flush()
  assert.equal(form.needsBoardChoice, true)
  assert.equal(form.confirmedBoard.identified, false)
  assert.deepEqual(requests, [
    {port:'COM8',board:'CHEAP_YELLOW_DISPLAY',baud:460800},
    {port:'COM8',board:'ESP32_C6_LCD_147',baud:460800}
  ])
})

test('changing ports discards the retained identified model before retrying installation', async t => {
  const {form,state,installs} = await mount(t)
  form.showInstall = true
  state.identity = null
  state.stage = 'failed'
  await form.poll(); await flush()
  assert.equal(form.identifiedBoard.value, 'JC4827W543')
  assert.equal(form.needsBoardChoice, false)

  form.port = 'COM9'
  await form.selectPort(); await flush()
  assert.equal(form.identifiedBoard, null)
  assert.equal(form.confirmedBoard, null)
  assert.equal(form.needsBoardChoice, true)
  assert.equal(form.board, '')
  assert.equal(form.installBoard, '')
  assert.equal(form.canInstall, false)
  form.goToStep(2)
  await form.install()
  assert.equal(installs(), 0)
})

test('a detected normal boot mode gives direct download-mode guidance while connection retries continue', async t => {
  const {form} = await mount(t)
  form.showInstall = true
  for (const {value:board} of form.boardItems) {
    form.state = {...form.state,identity:null,busy:true,stage:'connecting_manual',bootMode:'0x13',package:{board}}
    await flush()
    assert.equal(form.stageLabel, 'Put your display in download mode')
    assert.equal(form.installationProgress.label, 'Put your display in download mode')
    assert.equal(form.installationProgress.percent, null)
    assert.match(form.installationProgress.detail, /hold BOOT, press and release RESET\/EN, then release BOOT/i)
    assert.match(form.installationProgress.detail, /We[’']re still trying to connect\./)
    assert.doesNotMatch(form.installationProgress.detail, /^If\b/i)
    assert.equal(form.installationActive, true)
    assert.equal(form.locked, true)
    assert.equal(form.canInstall, false)
    assert.equal(form.compatible, false)
    for (const step of [1, 3, 4]) {
      form.goToStep(step)
      assert.equal(form.step, 2)
    }
  }
})

test('reopening setup during a manual-boot connection attempt restores the installation and same-port portrait', async t => {
  const {form} = await mount(t, {}, {
    port:'COM8',identity:null,busy:true,stage:'connecting_manual',bootMode:'0x13',
    package:{board:'CHEAP_YELLOW_DISPLAY',version:'1.1.42',source:'github'}
  })
  assert.equal(form.showInstall, true)
  assert.equal(form.installationStarted, true)
  assert.equal(form.installationActive, true)
  assert.equal(form.panel, 'install')
  assert.equal(form.step, 2)
  assert.equal(form.locked, true)
  assert.equal(form.detectedBoard.value, 'CHEAP_YELLOW_DISPLAY')
  assert.equal(form.identity, null)
  assert.equal(form.compatible, false)
  assert.equal(form.installationProgress.label, 'Put your display in download mode')
})

test('the download-mode animation is limited to manual connection and clears when flashing advances', async t => {
  const guide = descriptor.template.content.match(/<BootModeGuide\b([^>]*?)\/>/)
  assert.ok(guide, 'manual connection displays the animated BOOT and RESET guide')
  const condition = guide[1].match(/\bv-if="([^"]+)"/)?.[1]
  assert.ok(condition, 'the download-mode animation has an explicit visibility condition')
  const visible = new Function('state', `return Boolean(${condition})`)
  const {form} = await mount(t)
  form.showInstall = true
  form.state = {...form.state,identity:null,busy:true,stage:'connecting_manual',bootMode:'0x13',package:{board:'CHEAP_YELLOW_DISPLAY'}}
  await flush()
  assert.equal(visible(form.state), true)

  for (const [stage,phase] of [
    ['writing_and_verifying','writing'],['writing_and_verifying','verifying'],['restarting'],['identifying']
  ]) {
    // Retain the last boot-mode report to ensure the stage removes stale guidance.
    form.state = {...form.state,stage,progress:phase ? {phase,percent:50,verified:2,total:4} : null}
    await flush()
    assert.equal(visible(form.state), false)
    assert.doesNotMatch(form.installationProgress.detail, /\bBOOT\b|\bRESET\/EN\b|still trying to connect/)
    assert.equal(form.installationActive, true)
    assert.equal(form.locked, true)
  }

  form.state = {...form.state,stage:'connecting',bootMode:null,progress:null}
  await flush()
  assert.equal(visible(form.state), false)
  assert.equal(form.installationProgress.label, 'Connecting to your display')
  assert.match(form.installationProgress.detail, /^If connection takes too long,/)
})
