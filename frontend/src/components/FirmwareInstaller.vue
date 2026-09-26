<script setup>
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import UsbWifiSetup from './UsbWifiSetup.vue'
import SetupConnection from './SetupConnection.vue'
import { firmwareStatus } from '../firmwareStatus.js'
const emit = defineEmits(['open-display'])
const desktop = window.espImageServerDesktop
const available = Boolean(desktop?.firmwareLibrary && desktop?.refreshFirmwareIdentity)
const state = ref({ busy: false, stage: 'idle', package: null, error: '', log: '' })
const ports = ref([]), port = ref(''), board = ref(''), baud = ref(460800)
const pending = ref(false), error = ref(''), confirmed = ref(false)
const library = ref({ packages: [], issues: [], directory: '', checkedAt: null })
const onlineAvailable = Boolean(desktop?.firmwareReleases)
const source = ref(onlineAvailable ? 'github' : 'local')
const download = ref({ busy: false, download: null })
const libraryBusy = ref(false), libraryError = ref('')
const reviewed = ref(false), showInstall = ref(false), manageWifi = ref(false), wifiEditing = ref(false)
const serverReady = ref(false)
const installationStarted = ref(false)
let timer, disposed = false, epoch = 0, lastPorts = 0, lastIdentity = 0, autoAttempts = 0, wasBusy = false
const locked = computed(() => pending.value || state.value.busy || download.value.busy)
const identity = computed(() => state.value.identity?.port === port.value ? state.value.identity : null)
const compatible = computed(() => ['wifi_scan', 'wifi_connect', 'wifi_cancel', 'wifi_status'].every(c => identity.value?.capabilities?.includes(c)))
const update = computed(() => firmwareStatus(identity.value || (board.value ? { board_target: board.value, firmware_version: '0.0.0' } : null),
  library.value))
const panel = computed(() => showInstall.value ? 'install' : !identity.value ? 'connect' : !reviewed.value ? 'firmware' :
  manageWifi.value || !identity.value.wifi_connected ? 'wifi' : 'connection')
const step = computed(() => ({ connect: 1, install: 2, firmware: 2, wifi: 3, connection: 4 }[panel.value]))
const canInstall = computed(() => available && !locked.value && confirmed.value && port.value && state.value.package && board.value === state.value.package.board)
const boardItems = [
  { title: 'JC4827W543 (480 × 272)', value: 'JC4827W543', image: '/board-catalog/JC4827W543.png' }, { title: 'Waveshare ST7701 (320 × 820)', value: 'ST7701_320X820', image: '/board-catalog/ST7701_320X820.png' },
  { title: 'ESP32-C6 LCD 1.47 (172 × 320)', value: 'ESP32_C6_LCD_147', image: '/board-catalog/ESP32_C6_LCD_147.png' }, { title: 'Cheap Yellow Display (240 × 320)', value: 'CHEAP_YELLOW_DISPLAY', image: '/board-catalog/CHEAP_YELLOW_DISPLAY.png' },
  { title: 'Waveshare ESP32-S3 AMOLED 1.43 (466 × 466)', value: 'ESP32_S3_AMOLED_143', image: '/board-catalog/ESP32_S3_AMOLED_143.png' }
]
const detectedBoard = computed(() => boardItems.find(item => item.value === identity.value?.board_target))
const stageLabel = computed(() => ({ idle: 'Choose a firmware package', validating: 'Checking firmware files', ready: 'Ready to install',
  connecting: 'Connecting to your display', writing_and_verifying: 'Writing and verifying firmware', restarting: 'Restarting your display',
  identifying: 'Checking firmware startup', boot_verified: 'Firmware installed and startup verified',
  written: 'Write verified — startup still needs checking', failed: 'Installation needs attention' }[state.value.stage] || state.value.stage))
const updateText = computed(() => libraryBusy.value ? 'Checking for firmware updates…' : ({ unknown: 'Updates haven’t been checked.', missing: `No firmware for this display was found ${source.value === 'github' ? 'on GitHub' : 'in your local library'}.`,
  current: `Firmware is up to date: ${identity.value?.firmware_version}`,
  newer: `Installed ${identity.value?.firmware_version} is newer than the available releases.`,
  update: `Update available: ${identity.value?.firmware_version} → ${update.value.latest?.version}` }[update.value.kind]))
async function call(method, payload) {
  const result = await desktop[method](payload)
  if (!result.ok) throw new Error(result.error)
  return result.value
}
async function perform(action) {
  if (pending.value) return
  pending.value = true; error.value = ''
  try { await action() } catch (e) { error.value = e.message }
  finally { pending.value = false }
}
async function loadLibrary(method) {
  if (libraryBusy.value) return
  if (method === 'chooseFirmwareLibrary') source.value = 'local'
  method ||= source.value === 'github' ? 'checkFirmwareReleases' : 'checkFirmwareLibrary'
  libraryBusy.value = true; libraryError.value = ''
  try { library.value = await call(method) } catch (e) { libraryError.value = e.message; library.value.checkedAt = null }
  finally { libraryBusy.value = false }
}
function resetFlow() {
  reviewed.value = false; showInstall.value = false; manageWifi.value = false; wifiEditing.value = false
  confirmed.value = false; serverReady.value = false; autoAttempts = 0; lastIdentity = Date.now()
  installationStarted.value = false
}
async function checkPorts() {
  ports.value = await call('firmwarePorts')
  if (port.value && !ports.value.some(p => p.port === port.value) && !state.value.busy) {
    port.value = ''; epoch++; resetFlow(); state.value = await call('selectFirmwarePort', { port: '' })
  }
}
async function selectPort() {
  epoch++; resetFlow()
  await perform(async () => { state.value = await call('selectFirmwarePort', { port: port.value }) })
}
async function identify() {
  await perform(async () => {
    state.value = await call('identifyFirmware', { port: port.value })
    if (identity.value) board.value = identity.value.board_target
    lastIdentity = Date.now(); autoAttempts = 0
  })
}
async function refreshConnection() {
  lastIdentity = Date.now(); autoAttempts++
  await perform(async () => { state.value = await call('refreshFirmwareIdentity', { port: port.value }) })
}
async function reviewUpdate() {
  await perform(async () => {
    const pkg = update.value.latest
    confirmed.value = false
    state.value = pkg.source === 'github' ? await call('selectReleaseFirmware', { id: pkg.id, board: pkg.board,
      port: port.value }) : await call('selectLibraryFirmware', { directory: pkg.directory })
    board.value = pkg.board; showInstall.value = true
  })
}
async function choosePackage() {
  confirmed.value = false
  await perform(async () => { state.value = await call('chooseFirmwarePackage') })
}
async function install() {
  await perform(async () => { state.value = await call('installFirmware', { port: port.value, board: board.value, baud: baud.value }); installationStarted.value = true; confirmed.value = false; autoAttempts = 0 })
}
function continueSetup() { reviewed.value = true; manageWifi.value = false; lastIdentity = 0; autoAttempts = 0 }
function wifiState(next) { state.value = next; lastIdentity = Date.now(); autoAttempts = 0 }
async function poll() {
  const token = epoch
  try {
    if (onlineAvailable) download.value = await call('firmwareDownloadState')
    const next = await call('firmwareState')
    if (!pending.value && token === epoch) {
      state.value = next
      if (installationStarted.value && next.stage === 'boot_verified' && next.identity) port.value = next.identity.port
      if (wasBusy && !next.busy) { lastIdentity = Date.now(); autoAttempts = 0 }
      wasBusy = next.busy
      if (installationStarted.value && next.stage === 'boot_verified' && compatible.value) {
        showInstall.value = false; reviewed.value = true; lastIdentity = Date.now(); autoAttempts = 0
        installationStarted.value = false
      }
    }
    if (!locked.value && Date.now() - lastPorts > 3000) { lastPorts = Date.now(); await checkPorts() }
    if (!locked.value && identity.value?.wifi_configured && !identity.value.wifi_connected && reviewed.value && !wifiEditing.value && !manageWifi.value && !showInstall.value && autoAttempts < 3 && Date.now() - lastIdentity > 10000) await refreshConnection()
  } catch (e) { error.value = e.message }
  if (!disposed) timer = window.setTimeout(poll, 750)
}
watch(() => identity.value?.hardware_id, (next, previous) => {
  if (next && previous && next !== previous) resetFlow()
  if (!next) { serverReady.value = false; reviewed.value = false; manageWifi.value = false; wifiEditing.value = false }
})
onMounted(async () => {
  if (!available) return
  void loadLibrary(onlineAvailable ? 'firmwareReleases' : 'firmwareLibrary')
  await perform(async () => {
    state.value = await call('firmwareState'); port.value = state.value.selectedPort || state.value.identity?.port || ''
    if (state.value.identity) board.value = state.value.identity.board_target
    if (onlineAvailable) download.value = await call('firmwareDownloadState')
    if (!download.value.busy) await checkPorts()
  })
  if (!disposed) void poll()
})
onUnmounted(() => { disposed = true; window.clearTimeout(timer) })
</script>

<template>
  <v-card class="mx-auto" max-width="800">
    <v-card-text class="pa-6">
      <div class="d-flex align-center ga-3 mb-2"><v-icon icon="mdi-monitor" size="28" /><h1 class="text-h5">Set up display</h1></div>
      <p class="text-medium-emphasis mb-6">{{ identity ? identity.board_name : 'Connect your display. We’ll guide you through the rest.' }}</p>
      <ol class="setup-steps mb-6" aria-label="Display setup progress">
        <li v-for="(title, index) in ['Connect', 'Firmware', 'Wi-Fi', 'Ready']" :key="title" :aria-current="step === index + 1 ? 'step' : undefined" :class="{ current: step === index + 1, complete: step > index + 1 }"><span>{{ step > index + 1 ? '✓' : index + 1 }}</span>{{ title }}</li>
      </ol>
      <v-alert v-if="!available" type="info" variant="tonal">Open the updated ESPImageServer desktop app to set up a USB display. Your browser can manage displays already on the network.</v-alert>
      <template v-else>
        <div v-if="identity && panel !== 'connect'" class="setup-summary mb-5"><span>USB connected · {{ identity.board_name }}</span><v-btn variant="text" size="small" :disabled="locked" @click="port = ''; selectPort()">Change display</v-btn></div>
        <figure v-if="detectedBoard && ['firmware', 'install'].includes(panel)" class="detected-board mb-5">
          <img :src="detectedBoard.image" :alt="detectedBoard.title" class="board-photo" />
          <figcaption class="text-body-2 mt-2">{{ detectedBoard.title }}</figcaption>
        </figure>
        <v-alert v-if="error || state.error || state.identityError" type="error" variant="tonal" class="mb-4">{{ error || state.error || state.identityError }}</v-alert>
        <v-sheet v-if="download.busy" border rounded class="pa-4 mb-4" role="status" aria-live="polite">
          <p class="mb-3">{{ download.download?.stage === 'validating' ? 'Checking downloaded firmware…' : 'Downloading firmware from GitHub…' }}</p>
          <v-progress-linear :indeterminate="!download.download?.total || download.download?.stage === 'validating'" :model-value="100 * (download.download?.received || 0) / (download.download?.total || 1)" />
          <p class="text-body-2 mt-3">Your display will be changed only after you review and confirm installation.</p>
          <v-btn class="mt-2" variant="text" @click="call('cancelFirmwareDownload')">Cancel download</v-btn>
        </v-sheet>
        <section v-if="panel === 'connect'">
          <h2 class="text-h6 mb-2">Connect your display with a USB data cable</h2><p class="mb-5">Select its USB port, then check the display. Close Arduino Serial Monitor first.</p>
          <v-select v-model="port" :items="ports" item-title="label" item-value="port" label="USB display" :disabled="locked" no-data-text="No display found. Check the cable, then refresh." @update:model-value="selectPort" />
          <div class="setup-actions"><v-btn color="primary" :disabled="locked || !port" :loading="pending" @click="identify">Check display</v-btn><v-btn variant="text" :disabled="locked" @click="perform(checkPorts)">Refresh ports</v-btn></div>
          <v-btn v-if="state.identityError" class="mt-4" variant="tonal" :disabled="locked || !port" @click="showInstall = true">Install firmware on this display</v-btn>
        </section>
        <section v-if="panel === 'firmware'">
          <h2 class="text-h6 mb-2">{{ compatible ? 'Check for firmware updates' : 'Install compatible firmware' }}</h2><p class="mb-4">Installed version: <strong>{{ identity.firmware_version }}</strong></p>
          <v-alert :type="update.kind === 'current' ? 'success' : 'info'" variant="tonal" class="mb-4">{{ updateText }}</v-alert>
          <details v-if="update.latest?.notes" class="mb-4"><summary>What’s in version {{ update.latest.version }}</summary><p class="mt-3 release-notes">{{ update.latest.notes }}</p></details>
          <p v-if="source === 'github'" class="mb-4">Firmware comes directly from the official GitHub releases. The app downloads and checks the files for you.</p>
          <p v-else-if="!library.directory" class="mb-4">Choose a local firmware library to find packages for this display.</p>
          <div class="setup-actions mb-4">
            <v-btn v-if="update.kind === 'update'" color="primary" :disabled="locked || libraryBusy" @click="reviewUpdate">Review update to {{ update.latest.version }}</v-btn>
            <v-btn v-else-if="source === 'local' && !library.directory" color="primary" :loading="libraryBusy" :disabled="locked" @click="loadLibrary('chooseFirmwareLibrary')">Choose firmware library</v-btn>
            <v-btn v-else :variant="update.kind === 'current' && compatible ? 'text' : 'flat'" :loading="libraryBusy" :disabled="locked" @click="loadLibrary()">Check for updates</v-btn>
            <v-btn v-if="compatible" :color="update.kind === 'current' ? 'primary' : undefined" :variant="update.kind === 'current' ? 'flat' : 'text'" :disabled="locked" @click="continueSetup">{{ update.kind === 'update' ? 'Continue with current version' : 'Continue' }}</v-btn>
          </div>
          <v-btn variant="text" :disabled="locked" @click="showInstall = true">{{ compatible ? 'Reinstall or choose other firmware' : 'Choose firmware' }}</v-btn>
        </section>
        <section v-if="panel === 'install'">
          <h2 class="text-h6 mb-4">{{ state.busy ? stageLabel : 'Review firmware installation' }}</h2>
          <fieldset v-if="!identity" class="board-picker mb-4" :disabled="locked">
            <legend class="text-subtitle-1 mb-2">Choose your physical display model</legend>
            <p class="text-body-2 text-medium-emphasis mb-3">Match the photo and model name to your board.</p>
            <div class="board-grid">
              <label v-for="item in boardItems" :key="item.value" class="board-option" :class="{ selected: board === item.value }">
                <img :src="item.image" :alt="item.title" class="board-photo" />
                <span class="board-option-label"><input v-model="board" type="radio" name="firmware-board" :value="item.value" @change="confirmed = false" /><span>{{ item.title }}</span></span>
              </label>
            </div>
          </fieldset><p v-else class="mb-3">{{ identity.board_name }} · Installed {{ identity.firmware_version }}</p>
          <p v-if="!identity" class="mb-3">USB port: {{ port || 'Not selected' }}. Choose the physical display model above before installing.</p>
          <div v-if="source === 'github' && !state.busy" class="mb-4">
            <v-btn v-if="update.latest && !(state.package?.source === 'github' && state.package?.board === update.latest.board && state.package?.version === update.latest.version)" color="primary" variant="tonal" :disabled="locked || libraryBusy" @click="reviewUpdate">Download firmware {{ update.latest.version }}</v-btn>
            <p v-else-if="!update.latest && (board || identity)" class="mb-3">{{ libraryBusy ? 'Checking GitHub for this display…' : 'No matching release found. Check again, or choose a local package below.' }}</p>
          </div>
          <v-sheet v-if="state.package" border rounded class="pa-4 mb-4"><strong>{{ state.package.board }} · Version {{ state.package.version }}</strong><p class="mt-1">{{ state.package.source === 'github' ? 'Downloaded from GitHub. Files checked and ready.' : 'Package files checked and ready.' }}</p></v-sheet>
          <details v-if="update.latest?.notes" class="mb-4"><summary>Release notes for {{ update.latest.version }}</summary><p class="mt-3 release-notes">{{ update.latest.notes }}</p></details>
          <details v-if="!state.busy" class="mb-4"><summary>Use a local firmware package</summary><v-btn variant="text" class="mt-2" :disabled="locked" @click="choosePackage">Choose firmware folder</v-btn></details>
          <v-alert v-if="state.package && board && board !== state.package.board" type="error" class="mb-4">This package does not match the display model.</v-alert>
          <template v-if="state.package && !state.busy"><v-alert type="warning" variant="tonal" class="mb-3">This replaces the display’s firmware. Settings may be lost if its old partition layout differs. SD-card files are preserved. Keep USB connected until installation finishes.</v-alert><v-checkbox v-model="confirmed" label="Install this firmware on the selected display." :disabled="locked" hide-details class="mb-4" /><v-btn color="primary" :disabled="!canInstall" @click="install">Install {{ state.package.version }}</v-btn></template>
          <div v-if="state.busy || ['written', 'failed', 'boot_verified'].includes(state.stage)" role="status" class="my-4">{{ stageLabel }}</div><v-progress-linear v-if="state.busy" indeterminate class="my-4" />
          <p v-if="state.stage === 'written'" class="mb-3">The write passed verification and restart was requested. Check the screen, then check the display again to verify startup.</p>
          <v-btn v-if="state.stage === 'written'" class="mr-2" :disabled="locked" @click="showInstall = false; identify()">Check display after restart</v-btn><v-btn class="ml-2" variant="text" :disabled="locked" @click="showInstall = false">Back</v-btn>
          <details class="mt-5"><summary>Advanced installation details</summary><v-select v-model="baud" class="mt-4" label="USB transfer speed" :items="[{title:'Standard (460800)', value:460800}, {title:'Slower — retry failed transfers (115200)',value:115200}]" :disabled="locked" /><p v-if="state.package" class="setup-path">{{ state.package.directory }} · {{ state.package.chip }} · {{ state.package.flashBytes / 1048576 }} MB · {{ state.package.files.length }} binaries</p></details>
        </section>
        <section v-if="panel === 'wifi'">
          <UsbWifiSetup :identity="identity" :selected-port="port" :state="state.wifi" :locked="locked" @state="wifiState" @editing="wifiEditing = $event" />
          <p v-if="identity.wifi_configured && !identity.wifi_connected && !wifiEditing && !manageWifi" class="mt-3 text-body-2">{{ autoAttempts < 3 ? 'We’ll check the connection automatically after the board restarts.' : 'The board has not reported a connection yet. Check it again or change the saved network.' }}</p>
          <div class="setup-actions mt-4"><v-btn v-if="identity.wifi_connected" color="primary" :disabled="locked" @click="manageWifi = false">Continue</v-btn><v-btn v-else-if="identity.wifi_configured" variant="tonal" :disabled="locked || wifiEditing" @click="refreshConnection">Check connection</v-btn><v-btn variant="text" :disabled="locked" @click="reviewed = false">Back to firmware</v-btn></div>
        </section>
        <SetupConnection v-if="identity && compatible && reviewed" v-show="panel === 'connection'" :identity="identity" :selected-port="port" :locked="locked || panel !== 'connection'" @ready="serverReady = $event" @open-display="emit('open-display', $event)" />
        <div v-if="panel === 'connection'" class="mt-4"><p class="mb-3">Firmware {{ identity.firmware_version }} <span v-if="update.kind === 'update'">· Update {{ update.latest.version }} available</span></p><div class="setup-actions"><v-btn variant="text" :disabled="locked" @click="manageWifi = true">Manage Wi-Fi</v-btn><v-btn variant="text" :disabled="locked" @click="reviewed = false; loadLibrary()">Firmware updates</v-btn></div></div>
        <details v-if="['firmware', 'install'].includes(panel)" class="mt-5"><summary>Firmware source and advanced options</summary>
          <v-select v-model="source" class="mt-4" label="Firmware source" :items="[{title:'GitHub — official releases',value:'github',props:{disabled:!onlineAvailable}},{title:'Local firmware library',value:'local'}]" :disabled="locked || libraryBusy" @update:model-value="library = {packages:[],issues:[]}; loadLibrary(source === 'github' ? 'firmwareReleases' : 'firmwareLibrary')" />
          <p v-if="!onlineAvailable" class="mb-3">Restart the updated desktop app to enable GitHub downloads.</p>
          <p v-if="source === 'local'" class="my-3 setup-path">{{ library.directory || 'No folder selected' }}</p>
          <p v-if="library.checkedAt" class="mb-3 text-caption">Last checked: {{ new Date(library.checkedAt).toLocaleString() }}</p>
          <v-btn variant="text" :disabled="locked || libraryBusy" :loading="libraryBusy" @click="loadLibrary()">Check for updates</v-btn>
          <v-btn v-if="source === 'local'" variant="tonal" :disabled="locked || libraryBusy" @click="loadLibrary('chooseFirmwareLibrary')">{{ library.directory ? 'Change library folder' : 'Choose library folder' }}</v-btn>
        </details>
        <v-alert v-if="libraryError || library.error" type="warning" variant="tonal" class="mt-4">{{ libraryError || library.error }}</v-alert>
        <details v-if="panel === 'firmware' && library.issues?.length" class="mt-3"><summary>{{ library.issues.length }} package(s) could not be used</summary><p v-for="issue in library.issues" :key="issue.folder" class="mt-2">{{ issue.folder }}: {{ issue.message }}</p></details>
        <details v-if="identity" class="mt-5"><summary>Device details</summary><p class="mt-3">{{ identity.port }} · Hardware ID {{ identity.hardware_id }} · {{ identity.width }} × {{ identity.height }} · Firmware {{ identity.firmware_version }}</p><v-btn variant="text" :disabled="locked" @click="refreshConnection">Refresh device information</v-btn></details>
        <details v-if="panel !== 'connection' || !serverReady" class="mt-5" :open="state.stage === 'failed' || Boolean(state.identityError)"><summary>Connection help and recovery</summary><p class="mt-3">Use the board’s data USB connector and a data cable. Close other apps using the USB serial port.</p><p class="mt-3">If flashing cannot connect: hold BOOT, press and release RESET/EN, then release BOOT. Without RESET, reconnect USB while holding BOOT. Refresh ports and check the display again if its port name changes.</p><p class="mt-3">After an interrupted write, enter bootloader mode and reinstall the complete package. Try the slower USB speed if transfers fail. No full-chip erase is performed.</p></details>
        <details v-if="state.log" class="mt-4"><summary>Installation log</summary><pre class="firmware-log mt-3">{{ state.log }}</pre></details>
      </template>
    </v-card-text>
  </v-card>
</template>

<style scoped>
.board-picker { border: 0; min-width: 0; }
.board-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 12px; }
.board-option { display: flex; flex-direction: column; border: 2px solid rgba(var(--v-theme-on-surface), .2); border-radius: 8px; padding: 10px; cursor: pointer; }
.board-option.selected { border-color: rgb(var(--v-theme-primary)); background: rgba(var(--v-theme-primary), .08); }
.board-option:focus-within { outline: 2px solid rgb(var(--v-theme-primary)); outline-offset: 3px; }
.board-picker:disabled .board-option { opacity: .6; cursor: default; }
.board-photo { display: block; width: 100%; height: 160px; object-fit: contain; background: white; border-radius: 4px; }
.board-option-label { display: flex; align-items: baseline; gap: 8px; padding-top: 10px; font-size: .875rem; }
.board-option-label input { accent-color: rgb(var(--v-theme-primary)); flex-shrink: 0; }
.detected-board { max-width: 420px; }
.detected-board .board-photo { height: 200px; }
@media (max-width: 480px) { .board-grid { grid-template-columns: 1fr; } }
.setup-steps { display: flex; gap: 12px; justify-content: space-between; list-style: none; padding: 0; }
.setup-steps li { display: flex; align-items: center; gap: 8px; color: rgb(var(--v-theme-on-surface), .6); }
.setup-steps span { width: 28px; height: 28px; border-radius: 50%; display: grid; place-items: center; background: rgb(var(--v-theme-on-surface), .08); }
.setup-steps .current { color: rgb(var(--v-theme-primary)); font-weight: 700; }
.setup-steps .current span { background: rgb(var(--v-theme-primary), .15); }
.setup-steps .complete { color: rgb(var(--v-theme-success)); }
.setup-summary, .setup-actions { display: flex; flex-wrap: wrap; align-items: center; gap: 10px; }
.setup-summary { justify-content: space-between; font-size: .875rem; border-bottom: 1px solid rgb(var(--v-theme-on-surface), .12); padding-bottom: 12px; }
.setup-path, .release-notes { overflow-wrap: anywhere; white-space: pre-wrap; }
summary { cursor: pointer; font-size: .875rem; }
.firmware-log { white-space: pre-wrap; overflow-wrap: anywhere; max-height: 240px; overflow: auto; font-size: 12px; }
@media (max-width: 480px) { .setup-steps { gap: 6px; } .setup-steps li { flex-direction: column; font-size: .75rem; } }
</style>
