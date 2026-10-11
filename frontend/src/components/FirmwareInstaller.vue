<script setup>
import BoardShopping from './BoardShopping.vue'
import FirmwareReleaseNotes from './FirmwareReleaseNotes.vue'
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import UsbWifiSetup from './UsbWifiSetup.vue'
import SetupConnection from './SetupConnection.vue'
import { firmwareStatus } from '../firmwareStatus.js'
const emit = defineEmits(['generate'])
const desktop = window.espImageServerDesktop
const available = Boolean(desktop?.firmwareReleases && desktop?.refreshFirmwareIdentity)
const state = ref({ busy: false, stage: 'idle', package: null, error: '', log: '' })
const ports = ref([]), port = ref(''), board = ref(''), baud = ref(460800)
const confirmedBoard = ref(null)
const supportPanels = ref([])
const copyingLog = ref(false), logCopyStatus = ref('')
const pending = ref(false), error = ref('')
const library = ref({ packages: [], issues: [], directory: '', checkedAt: null })
const onlineAvailable = Boolean(desktop?.firmwareReleases)
const download = ref({ busy: false, download: null })
const libraryBusy = ref(false), libraryError = ref('')
const reviewed = ref(false), showInstall = ref(false), manageWifi = ref(false), wifiEditing = ref(false)
const serverReady = ref(false)
const checkingDisplay = ref(false)
const installationStarted = ref(false)
let timer, disposed = false, epoch = 0, lastPorts = 0, lastIdentity = 0, autoAttempts = 0, wasBusy = false
const locked = computed(() => pending.value || state.value.busy || download.value.busy)
const identity = computed(() => state.value.identity?.port === port.value ? state.value.identity : null)
const compatible = computed(() => ['wifi_scan', 'wifi_connect', 'wifi_cancel', 'wifi_status'].every(c => identity.value?.capabilities?.includes(c)))
const panel = computed(() => checkingDisplay.value ? 'connect' : showInstall.value ? 'install' : !identity.value ? 'connect' : !reviewed.value ? 'firmware' :
  manageWifi.value || !identity.value.wifi_connected ? 'wifi' : 'connection')
const step = computed(() => ({ connect: 1, install: 2, firmware: 2, wifi: 3, connection: 4 }[panel.value]))
const boardItems = [
  { title: 'JC4827W543 (480 × 272)', value: 'JC4827W543', image: '/ui/board-catalog/JC4827W543.png' }, { title: 'Waveshare ST7701 (320 × 820)', value: 'ST7701_320X820', image: '/ui/board-catalog/ST7701_320X820.png' },
  { title: 'ESP32-C6 LCD 1.47 (172 × 320)', value: 'ESP32_C6_LCD_147', image: '/ui/board-catalog/ESP32_C6_LCD_147.png' }, { title: 'Cheap Yellow Display (240 × 320)', value: 'CHEAP_YELLOW_DISPLAY', image: '/ui/board-catalog/CHEAP_YELLOW_DISPLAY.png' },
  { title: 'Waveshare ESP32-S3 AMOLED 1.43 (466 × 466)', value: 'ESP32_S3_AMOLED_143', image: '/ui/board-catalog/ESP32_S3_AMOLED_143.png' }
]
const detectedBoard = computed(() => confirmedBoard.value?.port === port.value
  ? boardItems.find(item => item.value === confirmedBoard.value.boardTarget) : null)
const identifiedBoard = computed(() => confirmedBoard.value?.identified ? detectedBoard.value : null)
const needsBoardChoice = computed(() => !identity.value && !identifiedBoard.value)
const installBoard = computed(() => identity.value?.board_target || identifiedBoard.value?.value || board.value)
const update = computed(() => firmwareStatus(identity.value || (installBoard.value ? { board_target: installBoard.value, firmware_version: '0.0.0' } : null),
  library.value))
const canInstall = computed(() => available && !locked.value && !libraryBusy.value && !libraryError.value && !library.value.error && port.value && update.value.latest?.source === 'github' && installBoard.value === update.value.latest.board)
const stageLabel = computed(() => ({ idle: 'Choose a firmware package', validating: 'Checking firmware files', ready: 'Ready to install',
  connecting: 'Connecting to your display', connecting_manual: 'Put your display in download mode', checking_identity: 'Checking the connected display', writing_and_verifying: 'Writing and verifying firmware', restarting: 'Restarting your display',
  identifying: 'Checking firmware startup', boot_verified: 'Firmware installed and startup verified',
  written: 'Write verified — startup still needs checking', failed: 'Installation needs attention' }[state.value.stage] || state.value.stage))
const installationActive = computed(() => download.value.busy || (step.value === 2 && (pending.value || state.value.busy)))
const installationProgress = computed(() => {
  if (download.value.busy) {
    const transfer = download.value.download
    const validating = transfer?.stage === 'validating'
    return { label: validating ? 'Checking downloaded firmware' : 'Downloading firmware from GitHub',
      percent: !validating && transfer?.total ? Math.min(100, Math.floor(100 * (transfer.received || 0) / transfer.total)) : null,
      detail: validating ? 'Checking that the files are complete and match your board.' : 'Getting the firmware files for your display.' }
  }
  if (pending.value && !state.value.busy) return { label: 'Preparing firmware installation', percent: null, detail: 'Getting your firmware ready.' }
  const progress = state.value.progress
  if (state.value.stage === 'writing_and_verifying') return {
    label: progress?.phase === 'verifying' ? 'Verifying firmware on your display' : progress?.phase === 'verified' ? 'Preparing the next firmware file' : 'Writing firmware to your display',
    percent: progress ? Math.floor(progress.percent) : null,
    detail: progress ? `${progress.verified} of ${progress.total} firmware files verified.` : 'Preparing the display for the USB transfer.'
  }
  return { label: stageLabel.value, percent: null, detail: ({
    validating: 'Checking the firmware files before making changes.',
    connecting: state.value.package?.board === 'CHEAP_YELLOW_DISPLAY'
      ? 'If connection takes too long, hold BOOT, press and release RESET/EN, then release BOOT. The app keeps the board in download mode through the firmware transfer.'
      : 'If connection takes too long, hold BOOT, press and release RESET/EN, then release BOOT.',
    connecting_manual: 'The board is not in download mode. Hold BOOT, press and release RESET/EN, then release BOOT. We’re still trying to connect.',
    checking_identity: 'Confirming that the connected display still matches your selection before writing firmware.',
    restarting: 'All firmware files are verified. Restarting your display.',
    identifying: 'Firmware upload complete. Waiting for the display to restart and confirm its new version.'
  }[state.value.stage] || 'Please wait while installation finishes.') }
})
const updateText = computed(() => libraryBusy.value ? 'Checking for firmware updates…' : ({ unknown: 'Updates haven’t been checked.', missing: `No firmware for this display was found on GitHub.`,
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
  method = method === 'firmwareReleases' ? 'firmwareReleases' : 'checkFirmwareReleases'
  libraryBusy.value = true; libraryError.value = ''
  try { library.value = await call(method) } catch (e) { libraryError.value = e.message; library.value.checkedAt = null }
  finally { libraryBusy.value = false }
}
async function copyInstallationLog() {
  const log = state.value.log
  if (!log || copyingLog.value) return
  copyingLog.value = true; logCopyStatus.value = ''
  const previousFocus = document.activeElement
  let input
  try {
    input = document.createElement('textarea')
    input.value = log
    input.setAttribute('readonly', '')
    input.style.cssText = 'position:fixed;opacity:0;pointer-events:none'
    document.body.append(input)
    input.select()
    if (!document.execCommand?.('copy')) {
      if (!navigator.clipboard?.writeText) throw new Error('Clipboard access is unavailable')
      await navigator.clipboard.writeText(log)
    }
    logCopyStatus.value = 'Installation log copied.'
  } catch {
    logCopyStatus.value = 'Could not copy. Select the log text and copy it manually.'
  } finally {
    input?.remove()
    previousFocus?.focus?.({ preventScroll: true })
    copyingLog.value = false
  }
}
function resetFlow() {
  confirmedBoard.value = null; board.value = ''; supportPanels.value = []
  checkingDisplay.value = false; reviewed.value = false; showInstall.value = false; manageWifi.value = false; wifiEditing.value = false
  serverReady.value = false; autoAttempts = 0; lastIdentity = Date.now()
  installationStarted.value = false
}
function goToStep(next) {
  if (locked.value || !available) return
  if (next === 1) {
    checkingDisplay.value = true; showInstall.value = false
  } else if (next === 2 && port.value) {
    checkingDisplay.value = false; reviewed.value = false; manageWifi.value = false
    showInstall.value = !identity.value; error.value = ''
  } else if (next === 3 && compatible.value) {
    checkingDisplay.value = false; showInstall.value = false; reviewed.value = true; manageWifi.value = true
  } else if (next === 4 && compatible.value && identity.value?.wifi_connected) {
    checkingDisplay.value = false; showInstall.value = false; continueSetup()
  }
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
    if (identity.value) { board.value = identity.value.board_target; checkingDisplay.value = false }
    lastIdentity = Date.now(); autoAttempts = 0
  })
}
async function refreshConnection() {
  lastIdentity = Date.now(); autoAttempts++
  await perform(async () => { state.value = await call('refreshFirmwareIdentity', { port: port.value }) })
}
async function install() {
  if (!canInstall.value) return
  const pkg = { ...update.value.latest }
  const selectedPort = port.value, selectedBoard = installBoard.value, selectedBaud = baud.value, token = epoch
  confirmedBoard.value = { port: selectedPort, boardTarget: selectedBoard, identified: Boolean(identifiedBoard.value) }
  showInstall.value = true
  await perform(async () => {
    state.value = await call('selectReleaseFirmware', { id: pkg.id, board: selectedBoard, port: selectedPort })
    if (disposed || token !== epoch || port.value !== selectedPort || installBoard.value !== selectedBoard) return
    if (state.value.package?.source !== 'github' || state.value.package?.board !== selectedBoard || state.value.package?.version !== pkg.version) {
      throw new Error('Downloaded firmware does not match the selected board and version. Nothing was installed.')
    }
    state.value = await call('installFirmware', { port: selectedPort, board: selectedBoard, baud: selectedBaud })
    installationStarted.value = true; autoAttempts = 0
  })
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
// Retain the identified model for installation retries; Wi-Fi still requires the live USB identity.
watch(identity, current => {
  if (current && boardItems.some(item => item.value === current.board_target)) {
    confirmedBoard.value = { port: current.port, boardTarget: current.board_target, identified: true }
  }
})
watch([() => state.value.stage, () => state.value.identityError], ([stage, identityError]) => {
  if (!identity.value && /disconnected|changed/i.test(identityError || '')) { confirmedBoard.value = null; board.value = '' }
  if (stage === 'failed' || identityError) {
    supportPanels.value = [...new Set([...supportPanels.value, 'recovery', ...(state.value.log ? ['log'] : [])])]
  }
})
watch(step, (next, previous) => {
  if (next === 2 && previous !== 2 && available) void loadLibrary()
})
watch(() => state.value.log, () => { logCopyStatus.value = '' })
onMounted(async () => {
  if (!available) return
  void loadLibrary('firmwareReleases')
  await perform(async () => {
    state.value = await call('firmwareState'); port.value = state.value.selectedPort || state.value.identity?.port || ''
    if (state.value.busy && ['validating', 'connecting', 'connecting_manual', 'checking_identity', 'writing_and_verifying', 'restarting', 'identifying'].includes(state.value.stage)) {
      showInstall.value = true; installationStarted.value = true
      if (state.value.port === port.value && boardItems.some(item => item.value === state.value.package?.board)) {
        board.value = state.value.package.board
        confirmedBoard.value = { port: port.value, boardTarget: board.value }
      }
    }
    if (state.value.identity) board.value = state.value.identity.board_target
    if (onlineAvailable) download.value = await call('firmwareDownloadState')
    if (!download.value.busy) await checkPorts()
  })
  if (!disposed) void poll()
})
onUnmounted(() => { disposed = true; window.clearTimeout(timer) })
</script>

<template>
  <v-stepper :model-value="step" class="setup-workspace" hide-actions :mobile="false" @update:model-value="goToStep">
    <v-card-text class="pa-6">
      <div class="d-flex align-center ga-3 mb-2"><v-icon icon="mdi-monitor" size="28" /><h1 class="text-h5">Set up display</h1></div>
      <p class="text-medium-emphasis mb-6">{{ identity ? identity.board_name : 'Connect your display. We’ll guide you through the rest.' }}</p>
      <v-stepper-header class="setup-stepper-header mb-6" aria-label="Display setup progress">
        <v-stepper-item :value="1" title="Check display" :subtitle="identity ? 'Display identified' : 'Choose a USB port'" :complete="Boolean(identity)" :editable="available && !locked" :disabled="!available || locked" color="primary" />
        <v-divider />
        <v-stepper-item :value="2" title="Install firmware" subtitle="Install or keep your version" :complete="compatible && reviewed" :editable="Boolean(available && port && !locked)" :disabled="!available || !port || locked" color="primary" />
        <v-divider />
        <v-stepper-item :value="3" title="Connect Wi-Fi" :subtitle="compatible ? 'Choose your network' : 'Requires compatible firmware'" :complete="compatible && reviewed && Boolean(identity?.wifi_connected)" :editable="compatible && !locked" :disabled="!compatible || locked" color="primary" />
        <v-divider />
        <v-stepper-item :value="4" title="Ready" subtitle="Connect to this app" :complete="serverReady" :editable="compatible && Boolean(identity?.wifi_connected) && !locked" :disabled="!compatible || !identity?.wifi_connected || locked" color="primary" />
      </v-stepper-header>
      <p class="text-body-2 text-medium-emphasis mb-4" role="status">Step {{ step }} of 4: {{ ['Check your display', 'Review firmware', 'Connect to Wi-Fi', 'Check the server connection'][step - 1] }}</p>
      <div class="setup-layout">
      <div class="setup-main">
      <v-alert v-if="!available" type="info" variant="tonal">Open the updated ESPImageServer desktop app to set up a USB display. Your browser can manage displays already on the network.</v-alert>
      <template v-else>
        <div v-if="identity && panel !== 'connect'" class="setup-summary mb-5"><span>USB connected · {{ identity.board_name }}</span><v-btn variant="text" size="small" :disabled="locked" @click="port = ''; selectPort()">Change display</v-btn></div>
        <v-alert v-if="error || state.error" type="error" variant="tonal" class="mb-4">{{ error || state.error }}</v-alert>
        <v-alert v-if="state.identityError && panel === 'connect'" type="info" variant="tonal" class="mb-4">We couldn't identify this display. You can retry, or continue to install firmware by choosing your board model in the next step.</v-alert>
        <v-sheet v-if="installationActive" border rounded class="pa-5 mb-4">
          <p class="text-h6 mb-3" role="status" aria-live="polite">{{ installationProgress.label }}</p>
          <v-progress-linear color="primary" height="12" rounded :indeterminate="installationProgress.percent === null" :model-value="installationProgress.percent ?? 0" :aria-label="installationProgress.label" />
          <p v-if="installationProgress.percent !== null" class="text-body-2 mt-2">{{ installationProgress.percent }}% {{ download.busy ? 'downloaded' : 'written' }}</p>
          <v-alert v-if="state.stage === 'connecting_manual'" type="warning" variant="tonal" class="mt-3" role="alert">{{ installationProgress.detail }}</v-alert>
          <p v-else class="mt-3" role="status" aria-live="polite">{{ installationProgress.detail }}</p>
          <p class="text-body-2 text-medium-emphasis mt-3">Keep the USB cable connected until installation finishes.</p>
          <v-btn v-if="download.busy" class="mt-2" variant="text" @click="call('cancelFirmwareDownload')">Cancel download</v-btn>
        </v-sheet>
        <section v-if="panel === 'connect'">
          <h2 class="text-h6 mb-2">Check your display</h2><p class="mb-5">Connect a USB data cable, select the port, then choose Check display. Close Serial Monitor first.</p>
          <v-select v-model="port" :items="ports" item-title="label" item-value="port" label="USB display" :disabled="locked" no-data-text="No display found. Check the cable, then refresh." @update:model-value="selectPort" />
          <div class="setup-actions"><v-btn color="primary" :disabled="locked || !port" :loading="pending" @click="identify">Check display</v-btn><v-btn variant="text" :disabled="locked" @click="perform(checkPorts)">Refresh ports</v-btn></div>
          <p class="mt-5 mb-3 text-body-2">New board or display not identified? Continue to choose your board and install firmware. Wi-Fi setup becomes available once compatible firmware is running.</p>
          <v-btn color="primary" variant="tonal" append-icon="mdi-arrow-right" :disabled="locked || !port" @click="goToStep(2)">Continue to firmware</v-btn>
        </section>
        <section v-if="['firmware', 'install'].includes(panel) && !installationActive">
          <h2 class="text-h6 mb-2">{{ state.busy ? stageLabel : compatible ? 'Firmware' : 'Install firmware' }}</h2>
          <p v-if="identity" class="mb-4">{{ identity.board_name }} ? Installed version {{ identity.firmware_version }}</p>
          <p v-else-if="identifiedBoard" class="mb-4">Detected display: <strong>{{ identifiedBoard.title }}</strong></p>
          <fieldset v-if="needsBoardChoice" class="board-picker mb-4" :disabled="locked">
            <legend class="text-subtitle-1 mb-2">Choose your physical display model</legend>
            <p class="text-body-2 text-medium-emphasis mb-3">Match the photo and model name to your board.</p>
            <div class="board-grid">
              <label v-for="item in boardItems" :key="item.value" class="board-option" :class="{ selected: board === item.value }">
                <img :src="item.image" :alt="item.title" class="board-photo" />
                <span class="board-option-label"><input v-model="board" type="radio" name="firmware-board" :value="item.value" /><span>{{ item.title }}</span></span>
              </label>
            </div>
          </fieldset>
          <p v-if="needsBoardChoice" class="mb-4">Choose the board connected to {{ port || 'your USB port' }}.</p>
          <v-progress-linear v-if="libraryBusy" indeterminate class="mb-4" aria-label="Checking for firmware" />
          <v-alert v-if="identity && !libraryBusy" :type="update.kind === 'current' ? 'success' : 'info'" variant="tonal" class="mb-4">{{ updateText }}</v-alert>
          <p v-if="!identity && installBoard && !update.latest && !libraryBusy && !libraryError && !library.error" class="mb-4">No matching firmware release is available for this board.</p>
          <template v-if="update.latest && !libraryBusy">
            <p class="text-subtitle-1 mb-3">{{ update.kind === 'update' && identity ? 'Update available' : 'Available firmware' }}: <strong>{{ update.latest.version }}</strong></p>
            <v-alert v-if="installBoard === 'CHEAP_YELLOW_DISPLAY'" type="info" variant="tonal" class="mb-4">For an update, keep the current firmware running until the app shows “Connecting to your display”. If needed, use BOOT and RESET at that step; the app will show the instructions.</v-alert>
            <v-alert type="warning" variant="tonal" class="mb-4">Installing firmware replaces the display's firmware. Settings may be lost if its old partition layout differs. SD-card files are preserved. Keep USB connected until installation finishes.</v-alert>
            <v-select v-model="baud" label="USB transfer speed" :items="[{title:'Standard (460800)', value:460800}, {title:'Slower ? retry failed transfers (115200)',value:115200}]" :disabled="locked" hint="Use Standard normally. Try Slower if firmware transfers fail." persistent-hint class="mb-4" />
          </template>
          <div v-if="!state.busy && !pending && !download.busy" class="setup-actions mt-4">
            <template v-if="update.kind === 'update' || !compatible">
              <v-btn color="primary" :disabled="!canInstall" @click="install">{{ identity && compatible ? 'Update to' : 'Install firmware' }}{{ update.latest ? ` ${update.latest.version}` : '' }}</v-btn>
              <v-btn v-if="compatible" variant="text" @click="continueSetup">Skip update</v-btn>
              <v-btn v-else variant="text" prepend-icon="mdi-arrow-left" @click="goToStep(1)">Back</v-btn>
            </template>
            <template v-else>
              <v-btn color="primary" append-icon="mdi-arrow-right" @click="goToStep(3)">Next: Wi-Fi</v-btn>
              <v-btn v-if="update.kind === 'current'" variant="text" :disabled="!canInstall" @click="install">Reinstall firmware</v-btn>
            </template>
          </div>
          <div v-if="state.busy || ['written', 'failed', 'boot_verified'].includes(state.stage)" role="status" class="my-4">{{ stageLabel }}</div>
          <p v-if="state.stage === 'written'" class="mb-3">Firmware was written, but startup could not be confirmed. Check the display after it restarts to continue.</p>
          <v-btn v-if="state.stage === 'written'" :disabled="locked" @click="showInstall = false; identify()">Check display after restart</v-btn>
        </section>
        <section v-if="panel === 'wifi'">
          <UsbWifiSetup :identity="identity" :selected-port="port" :state="state.wifi" :locked="locked" @state="wifiState" @editing="wifiEditing = $event" />
          <p v-if="identity.wifi_configured && !identity.wifi_connected && !wifiEditing && !manageWifi" class="mt-3 text-body-2">{{ autoAttempts < 3 ? 'We’ll check the connection automatically after the board restarts.' : 'The board has not reported a connection yet. Check it again or change the saved network.' }}</p>
          <div class="setup-actions mt-4"><v-btn v-if="identity.wifi_connected" color="primary" :disabled="locked" @click="manageWifi = false">Continue</v-btn><v-btn v-else-if="identity.wifi_configured" variant="tonal" :disabled="locked || wifiEditing" @click="refreshConnection">Check connection</v-btn><v-btn variant="text" :disabled="locked" @click="reviewed = false">Back to firmware</v-btn></div>
        </section>
        <SetupConnection v-if="identity && compatible && reviewed" v-show="panel === 'connection'" :identity="identity" :selected-port="port" :locked="locked || panel !== 'connection'" @ready="serverReady = $event" @generate="emit('generate', $event)" />
        <div v-if="panel === 'connection'" class="mt-4"><p class="mb-3">Firmware {{ identity.firmware_version }} <span v-if="update.kind === 'update'">· Update {{ update.latest.version }} available</span></p><div class="setup-actions"><v-btn variant="text" :disabled="locked" @click="manageWifi = true">Manage Wi-Fi</v-btn><v-btn variant="text" :disabled="locked" @click="reviewed = false; loadLibrary()">Firmware updates</v-btn></div></div>
        <v-alert v-if="libraryError || library.error" type="warning" variant="tonal" class="mt-4">
          {{ libraryError || library.error }}
          <v-btn variant="text" :disabled="locked || libraryBusy" :loading="libraryBusy" @click="loadLibrary()">Retry</v-btn>
        </v-alert>
      </template>
      </div>
      <aside class="setup-support" aria-label="Display information and help">
        <h2 class="text-h6 mb-4">{{ detectedBoard ? 'Your display' : 'Display setup help' }}</h2>
        <figure v-if="detectedBoard" class="detected-board mb-5">
          <img :src="detectedBoard.image" :alt="detectedBoard.title" class="board-photo" />
          <figcaption class="text-body-2 mt-2">{{ detectedBoard.title }}</figcaption>
        </figure>

        <p v-if="identity" class="text-body-2 mb-4">{{ identity.wifi_connected ? 'Connected to Wi-Fi' : 'Wi-Fi connection pending' }}</p>
        <BoardShopping v-if="!detectedBoard && !identity && !locked" />
        <v-expansion-panels v-model="supportPanels" multiple variant="accordion" class="setup-support-panels mt-5">
          <v-expansion-panel v-if="update.latest" value="release">
            <v-expansion-panel-title>Release information · {{ update.latest.version }}</v-expansion-panel-title>
            <v-expansion-panel-text>
              <FirmwareReleaseNotes v-if="update.latest.notes?.trim()" :release="update.latest" embedded />
              <p v-else class="text-body-2">Release notes are not available for this version.</p>
            </v-expansion-panel-text>
          </v-expansion-panel>
          <v-expansion-panel v-if="state.log" value="log">
            <v-expansion-panel-title>Installation log</v-expansion-panel-title>
            <v-expansion-panel-text>
              <div class="d-flex flex-wrap align-center ga-3 mb-3">
                <v-btn color="primary" variant="tonal" size="small" prepend-icon="mdi-content-copy" :loading="copyingLog" :disabled="!state.log" @click="copyInstallationLog">Copy log</v-btn>
                <span v-if="logCopyStatus" class="text-caption" role="status">{{ logCopyStatus }}</span>
              </div>
              <pre class="firmware-log" tabindex="0" aria-label="Installation log">{{ state.log }}</pre>
            </v-expansion-panel-text>
          </v-expansion-panel>
          <v-expansion-panel v-if="identity" value="device">
            <v-expansion-panel-title>Device details</v-expansion-panel-title>
            <v-expansion-panel-text>
              <p class="text-body-2">{{ identity.port }} · Hardware ID {{ identity.hardware_id }} · {{ identity.width }} × {{ identity.height }} · Firmware {{ identity.firmware_version }}</p>
              <v-btn class="mt-3" variant="text" :disabled="locked" @click="refreshConnection">Refresh device information</v-btn>
            </v-expansion-panel-text>
          </v-expansion-panel>
          <v-expansion-panel v-if="library.issues?.length" value="issues">
            <v-expansion-panel-title>{{ library.issues.length }} package(s) could not be used</v-expansion-panel-title>
            <v-expansion-panel-text><p v-for="issue in library.issues" :key="issue.folder" class="text-body-2 mb-2">{{ issue.folder }}: {{ issue.message }}</p></v-expansion-panel-text>
          </v-expansion-panel>
          <v-expansion-panel v-if="panel !== 'connection' || !serverReady || state.stage === 'failed' || state.identityError" value="recovery">
            <v-expansion-panel-title>Connection help and recovery</v-expansion-panel-title>
            <v-expansion-panel-text>
              <p class="text-body-2 mb-3">Use the board’s data USB connector and a data cable. Close other apps using the USB serial port.</p>
              <p class="text-body-2 mb-3">If flashing cannot connect: hold BOOT, press and release RESET/EN, then release BOOT. Without RESET, reconnect USB while holding BOOT. Refresh ports and check the display again if its port name changes.</p>
              <p class="text-body-2">After an interrupted write, enter bootloader mode and reinstall the complete package. Try the slower USB speed if transfers fail. No full-chip erase is performed.</p>
            </v-expansion-panel-text>
          </v-expansion-panel>
        </v-expansion-panels>
      </aside>
      </div>
    </v-card-text>
  </v-stepper>
</template>

<style scoped>
.setup-workspace { container-type: inline-size; }
.setup-stepper-header { display: grid; grid-template-columns: minmax(0, 1fr) 32px minmax(0, 1fr) 32px minmax(0, 1fr) 32px minmax(0, 1fr); box-shadow: none; border-bottom: 1px solid rgba(var(--v-theme-on-surface), .12); }
.setup-stepper-header > .v-divider { margin: 0; }
.setup-stepper-header :deep(.v-stepper-item) { padding: 24px 12px; min-width: 0; min-height: 104px; border-radius: 8px; }
.setup-stepper-header :deep(.v-stepper-item--selected) { background: rgba(var(--v-theme-primary), .07); }
.setup-stepper-header :deep(.v-stepper-item__content) { min-width: 0; }
/* Vuetify sets the step avatar's dimensions inline. */
.setup-stepper-header :deep(.v-stepper-item__avatar.v-avatar) { width: 44px !important; height: 44px !important; flex-shrink: 0; margin-inline-end: 12px; font-size: 1.25rem; font-weight: 600; }
.setup-stepper-header :deep(.v-stepper-item__avatar .v-icon) { font-size: 1.375rem; }
.setup-stepper-header :deep(.v-stepper-item__title) { font-size: 1.125rem; font-weight: 600; line-height: 1.3; white-space: normal; overflow-wrap: anywhere; }
.setup-stepper-header :deep(.v-stepper-item__subtitle) { margin-top: 4px; font-size: .9375rem; line-height: 1.4; white-space: normal; }
@container (max-width: 1000px) {
  .setup-stepper-header { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .setup-stepper-header > .v-divider { display: none; }
}
@container (max-width: 480px) {
  .setup-stepper-header { grid-template-columns: minmax(0, 1fr); }
  .setup-stepper-header :deep(.v-stepper-item) { min-height: 88px; padding: 16px 12px; }
}
.setup-layout { display: grid; grid-template-columns: minmax(0, 1fr); gap: 32px; }
.setup-main, .setup-support { min-width: 0; }
.setup-support { padding: 24px; border-radius: 8px; background: rgba(var(--v-theme-on-surface), .035); overflow-wrap: anywhere; }
@container (min-width: 1000px) {
  .setup-layout { grid-template-columns: minmax(0, 2fr) minmax(280px, 1fr); align-items: start; }
}

.board-picker { border: 0; min-width: 0; }
.board-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(min(100%, 220px), 1fr)); gap: 12px; }
.board-option { display: flex; flex-direction: column; border: 2px solid rgba(var(--v-theme-on-surface), .2); border-radius: 8px; padding: 10px; cursor: pointer; }
.board-option.selected { border-color: rgb(var(--v-theme-primary)); background: rgba(var(--v-theme-primary), .08); }
.board-option:focus-within { outline: 2px solid rgb(var(--v-theme-primary)); outline-offset: 3px; }
.board-picker:disabled .board-option { opacity: .6; cursor: default; }
.board-photo { display: block; width: 100%; height: 160px; object-fit: contain; background: white; border-radius: 4px; }
.board-option-label { display: flex; align-items: baseline; gap: 8px; padding-top: 10px; font-size: .875rem; }
.board-option-label input { accent-color: rgb(var(--v-theme-primary)); flex-shrink: 0; }
.detected-board { margin: 0; width: 100%; max-width: 420px; }
.detected-board .board-photo { height: 200px; }
.setup-support-panels :deep(.v-expansion-panel-title) { line-height: 1.4; }
.setup-support-panels :deep(.v-expansion-panel-text__wrapper) { min-width: 0; }
@media (max-width: 480px) { .board-grid { grid-template-columns: 1fr; } }
.setup-summary, .setup-actions { display: flex; flex-wrap: wrap; align-items: center; gap: 10px; }
.setup-summary { justify-content: space-between; font-size: .875rem; border-bottom: 1px solid rgb(var(--v-theme-on-surface), .12); padding-bottom: 12px; }
.setup-path { overflow-wrap: anywhere; white-space: pre-wrap; }
.firmware-log { white-space: pre-wrap; overflow-wrap: anywhere; max-height: 240px; overflow: auto; font-size: 12px; user-select: text; }
</style>
