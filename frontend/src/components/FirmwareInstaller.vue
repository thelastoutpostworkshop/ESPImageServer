<script setup>
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import UsbWifiSetup from './UsbWifiSetup.vue'
import SetupConnection from './SetupConnection.vue'

const emit = defineEmits(['open-display'])

const desktop = window.espImageServerDesktop
const available = Boolean(desktop?.installFirmware && desktop?.selectFirmwarePort && desktop?.startWifiSetup)
const state = ref({ busy: false, stage: 'idle', package: null, error: '', log: '' })
const ports = ref([])
const port = ref('')
const board = ref('')
const baud = ref(460800)
const confirmed = ref(false)
const error = ref('')
const pending = ref(false)
const showInstall = ref(false), serverReady = ref(false)
let timer, disposed = false, selectionEpoch = 0, lastPortCheck = 0
const boardItems = [
  { title: 'JC4827W543 (480 × 272)', value: 'JC4827W543' },
  { title: 'Waveshare ST7701 (320 × 820)', value: 'ST7701_320X820' },
  { title: 'ESP32-C6 LCD 1.47 (172 × 320)', value: 'ESP32_C6_LCD_147' },
  { title: 'Cheap Yellow Display (240 × 320)', value: 'CHEAP_YELLOW_DISPLAY' }
]
const locked = computed(() => pending.value || state.value.busy)
const wifiActive = computed(() => state.value.busy && ['opening', 'scanning', 'connecting', 'obtaining_ip'].includes(state.value.wifi?.stage))
const identity = computed(() => state.value.identity?.port === port.value ? state.value.identity : null)
const compatible = computed(() => ['wifi_scan', 'wifi_connect', 'wifi_cancel', 'wifi_status'].every(c => identity.value?.capabilities?.includes(c)))
const currentStep = computed(() => !identity.value ? 1 : !compatible.value ? 2 : !identity.value.wifi_connected ? 3 : 4)
watch(compatible, value => { if (value) showInstall.value = false })
const canInstall = computed(() => available && !locked.value && confirmed.value && port.value &&
  state.value.package && board.value === state.value.package.board)
const stageLabel = computed(() => ({
  idle: 'Choose a firmware package', validating: 'Checking firmware files', ready: 'Package validated',
  connecting: 'Connecting and checking the chip', writing_and_verifying: 'Writing and verifying firmware',
  restarting: 'Restarting the board', identifying: 'Waiting for firmware identification over USB',
  boot_verified: 'Firmware startup verified over USB', written: 'Firmware written and verified', failed: 'Installation needs attention'
}[state.value.stage] || state.value.stage))
async function call(method, payload) {
  const result = await desktop[method](payload)
  if (!result.ok) throw new Error(result.error)
  return result.value
}
async function perform(action) {
  pending.value = true; error.value = ''
  try { await action() } catch (e) { error.value = e.message }
  finally { pending.value = false }
}
async function checkPorts() {
  ports.value = await call('firmwarePorts')
  if (port.value && !ports.value.some(p => p.port === port.value)) {
    port.value = ''; selectionEpoch++; serverReady.value = false
    if (!state.value.busy && desktop.selectFirmwarePort) state.value = await call('selectFirmwarePort', { port: '' })
  }
}
async function refreshPorts() { await perform(checkPorts) }
async function selectPort() {
  selectionEpoch++; confirmed.value = false; serverReady.value = false
  await perform(async () => {
    if (desktop.selectFirmwarePort) state.value = await call('selectFirmwarePort', { port: port.value })
    else { state.value.identity = null; state.value.wifi = null }
  })
}
async function choosePackage() {
  confirmed.value = false
  await perform(async () => { state.value = await call('chooseFirmwarePackage') })
}
async function install() {
  await perform(async () => {
    state.value = await call('installFirmware', { port: port.value, board: board.value, baud: baud.value })
    confirmed.value = false
  })
}
async function identify() {
  await perform(async () => {
    state.value = await call('identifyFirmware', { port: port.value })
    if (identity.value) board.value = identity.value.board_target
    showInstall.value = !compatible.value
  })
}
async function poll() {
  const epoch = selectionEpoch
  try {
    if (!pending.value && Date.now() - lastPortCheck > 3000) { lastPortCheck = Date.now(); await checkPorts() }
    const next = await call('firmwareState')
    if (!pending.value && epoch === selectionEpoch) state.value = next
  } catch (e) { error.value = e.message }
  if (!disposed) timer = window.setTimeout(poll, 750)
}
onMounted(() => { if (available) { void refreshPorts(); void poll() } })
onUnmounted(() => { disposed = true; window.clearTimeout(timer) })
</script>

<template>
  <v-card class="mx-auto" max-width="960">
    <v-card-title class="d-flex align-center ga-2"><v-icon icon="mdi-usb-flash-drive-outline" />Set up display</v-card-title>
    <v-card-subtitle class="text-wrap">Connect a USB display, set up Wi-Fi, and confirm its connection to ESPImageServer.</v-card-subtitle>
    <v-card-text>
      <v-alert v-if="!available" type="info" variant="tonal" class="mb-5">
        USB display setup requires the ESPImageServer desktop app. The browser can manage displays already connected over the network. If this is an older desktop window, restart it after updating the app.
      </v-alert>
      <p class="mb-5">Connect your display with a USB data cable. Close Arduino Serial Monitor and other apps using its COM port.</p>
      <ol class="setup-steps mb-5" aria-label="Display setup progress">
        <li v-for="(title, index) in ['USB display', 'Firmware', 'Wi-Fi', serverReady ? 'Ready' : 'Server connection']" :key="index" :aria-current="currentStep === index + 1 ? 'step' : undefined" :class="{ 'font-weight-bold': currentStep === index + 1 }">{{ index + 1 }}. {{ title }}</li>
      </ol>
      <h3 class="text-subtitle-1 font-weight-bold mb-3">1. Choose the USB display</h3>
      <v-select v-model="port" :items="ports" item-title="label" item-value="port" label="USB / COM port" :disabled="!available || locked" hide-details="auto" no-data-text="No serial ports found. Check your cable and driver, then refresh." @update:model-value="selectPort" />
      <div class="d-flex flex-wrap ga-2 mt-2 mb-4">
        <v-btn variant="text" prepend-icon="mdi-refresh" :disabled="!available || locked" @click="refreshPorts">Refresh ports</v-btn>
        <v-btn color="primary" variant="tonal" prepend-icon="mdi-information-outline" :disabled="!desktop?.identifyFirmware || locked || !port" @click="identify">{{ identity ? 'Refresh USB identity' : 'Identify and continue' }}</v-btn>
      </div>
      <v-alert v-if="state.identityError" type="warning" variant="tonal" class="mb-4">{{ state.identityError }} You can install a compatible firmware package below.</v-alert>
      <v-alert v-if="state.identity && state.identity.port !== port && !locked" type="info" variant="tonal" class="mb-4">The board was identified on {{ state.identity.port }}. Select that port and identify it again to continue setup.</v-alert>
      <v-sheet v-if="identity" border rounded class="pa-4 mb-4" aria-live="polite">
        <div class="font-weight-bold">{{ identity.board_name }} · Firmware {{ identity.firmware_version }}</div>
        <div>{{ identity.port }} · Hardware ID {{ identity.hardware_id }} · {{ identity.width }} × {{ identity.height }}</div>
        <div>{{ identity.wifi_connected ? 'Wi-Fi connected' : identity.wifi_configured ? 'Wi-Fi saved, currently disconnected' : 'No saved Wi-Fi' }}</div>
        <div class="text-caption mt-2">Read directly from the running firmware over USB. Other connected displays are not selected automatically.</div>
      </v-sheet>
      <h3 class="text-subtitle-1 font-weight-bold mb-2">2. Check firmware</h3>
      <v-alert v-if="compatible" type="success" variant="tonal" class="mb-3">Compatible firmware is already running. Continue to Wi-Fi; no flashing is needed.</v-alert>
      <p v-else class="mb-3">Identify the board first. If firmware is missing or incompatible, install a package for its physical display model.</p>
      <v-btn variant="text" :disabled="locked" class="mb-3" @click="showInstall = !showInstall">{{ showInstall ? 'Hide firmware installation' : 'Install or update firmware' }}</v-btn>
      <v-sheet v-if="showInstall" border rounded class="pa-4">
      <v-select v-model="board" :items="boardItems" label="Physical display model" :disabled="!available || locked" hide-details="auto" @update:model-value="confirmed = false" />
      <v-btn class="my-4" variant="tonal" prepend-icon="mdi-folder-open-outline" :disabled="!available || locked" @click="choosePackage">Choose firmware folder</v-btn>
      <p class="text-body-2 text-medium-emphasis mb-4">Select the version folder containing manifest.json and the four binaries, for example JC4827W543 / 1.1.4.</p>
      <v-sheet v-if="state.package" rounded border class="pa-4 mb-4">
        <div class="text-subtitle-1 font-weight-bold">{{ state.package.board }} · Firmware {{ state.package.version }}</div>
        <div>{{ state.package.chip.toUpperCase() }} · {{ state.package.flashBytes / 1048576 }} MB flash · {{ state.package.files.length }} verified binaries</div>
        <div class="text-caption text-medium-emphasis mt-2 firmware-path">{{ state.package.directory }}</div>
        <v-alert v-if="board && board !== state.package.board" type="error" variant="tonal" class="mt-3">This package does not match your selected display model.</v-alert>
      </v-sheet>
      <v-select v-model="baud" label="USB transfer speed" :items="[{ title: 'Standard (460800)', value: 460800 }, { title: 'Slower — try if transfers fail (115200)', value: 115200 }]" :disabled="!available || locked" hide-details class="mb-4" />
      <v-alert type="warning" variant="tonal" class="mb-3">
        This installs the bootloader, partition table, and application. It replaces existing firmware; settings may be lost if the old partition layout differs. SD-card files are not changed. Keep USB connected until installation finishes.
      </v-alert>
      <v-checkbox v-model="confirmed" label="I checked the physical display model and COM port, and want to replace its firmware." :disabled="!available || locked || !state.package" hide-details />
      <v-btn class="my-4" color="primary" size="large" prepend-icon="mdi-download" :disabled="!canInstall" :loading="state.busy && !wifiActive" @click="install">Install firmware</v-btn>
      <div role="status" aria-live="polite" class="font-weight-medium mb-2">{{ stageLabel }}</div>
      <v-progress-linear v-if="state.busy && !wifiActive" indeterminate color="primary" rounded class="mb-4" aria-label="Firmware installation in progress" />
      <v-alert v-if="state.stage === 'written'" type="success" variant="tonal" class="mb-4">
        All four writes passed verification and a restart was requested. Check the physical screen for the expected board/version (and “No saved Wi-Fi” on an unconfigured board). Application startup has not been verified automatically.
      </v-alert>
      <v-alert v-if="state.stage === 'boot_verified'" type="success" variant="tonal" class="mb-4">
        All four writes passed verification. The running firmware now reports the expected board and version over USB.
      </v-alert>
      </v-sheet>
      <v-alert v-if="error || state.error" type="error" variant="tonal" class="my-4">{{ error || state.error }}</v-alert>
      <UsbWifiSetup v-if="identity" :identity="identity" :selected-port="port" :state="state.wifi" :locked="locked" @state="state = $event" />
      <SetupConnection v-if="identity && compatible" :identity="identity" :selected-port="port" :locked="locked" @ready="serverReady = $event" @open-display="emit('open-display', $event)" />
      <v-expansion-panels variant="accordion" class="mt-4">
        <v-expansion-panel title="Connection help and recovery">
          <v-expansion-panel-text>
            <p>Use the board's data/serial USB connector. A charge-only cable can power the display without creating a COM port. USB-to-UART boards may need their manufacturer's driver.</p>
            <p class="mt-3">If connection fails, use the selected board's BOOT and RESET/EN controls: hold BOOT, press and release RESET, then release BOOT. If there is no RESET button, reconnect USB while holding BOOT. Refresh ports if Windows assigns a different COM number, then retry. Consult the board's instructions for button and connector locations.</p>
            <p class="mt-3">After an interrupted write, reconnect in bootloader mode and install the complete package again. If transfer errors persist, select the slower speed. Automatic reset depends on your board's wiring; no full-chip erase is performed.</p>
          </v-expansion-panel-text>
        </v-expansion-panel>
      </v-expansion-panels>
      <details v-if="state.log" class="mt-4" open><summary>Installation log</summary><pre class="firmware-log mt-2">{{ state.log }}</pre></details>
    </v-card-text>
  </v-card>
</template>

<style scoped>
.setup-steps { display: flex; flex-wrap: wrap; gap: 8px 24px; list-style: none; padding: 0; }
.firmware-path { overflow-wrap: anywhere; }
.firmware-log { white-space: pre-wrap; overflow-wrap: anywhere; max-height: 300px; overflow: auto; font-size: 12px; padding: 12px; background: rgba(127,127,127,.08); border-radius: 6px; }
</style>
