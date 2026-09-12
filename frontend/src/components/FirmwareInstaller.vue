<script setup>
import { computed, onMounted, onUnmounted, ref } from 'vue'
import UsbWifiSetup from './UsbWifiSetup.vue'

const desktop = window.espImageServerDesktop
const available = Boolean(desktop?.installFirmware)
const state = ref({ busy: false, stage: 'idle', package: null, error: '', log: '' })
const ports = ref([])
const port = ref('')
const board = ref('')
const baud = ref(460800)
const confirmed = ref(false)
const error = ref('')
const pending = ref(false)
let timer, disposed = false
const boardItems = [
  { title: 'JC4827W543 (480 × 272)', value: 'JC4827W543' },
  { title: 'Waveshare ST7701 (320 × 820)', value: 'ST7701_320X820' },
  { title: 'ESP32-C6 LCD 1.47 (172 × 320)', value: 'ESP32_C6_LCD_147' },
  { title: 'Cheap Yellow Display (240 × 320)', value: 'CHEAP_YELLOW_DISPLAY' }
]
const locked = computed(() => pending.value || state.value.busy)
const wifiActive = computed(() => state.value.busy && ['opening', 'scanning', 'connecting', 'obtaining_ip'].includes(state.value.wifi?.stage))
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
async function refreshPorts() {
  await perform(async () => {
    ports.value = await call('firmwarePorts')
    if (!ports.value.some(p => p.port === port.value)) port.value = ''
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
  await perform(async () => { state.value = await call('identifyFirmware', { port: port.value }) })
}
async function poll() {
  try { state.value = await call('firmwareState') } catch (e) { error.value = e.message }
  if (!disposed) timer = window.setTimeout(poll, 750)
}
onMounted(() => { if (available) { void refreshPorts(); void poll() } })
onUnmounted(() => { disposed = true; window.clearTimeout(timer) })
</script>

<template>
  <v-card class="mx-auto" max-width="960">
    <v-card-title class="d-flex align-center ga-2"><v-icon icon="mdi-usb-flash-drive-outline" />Install firmware</v-card-title>
    <v-card-subtitle class="text-wrap">Install firmware, identify your display, and configure Wi-Fi over USB.</v-card-subtitle>
    <v-card-text>
      <v-alert v-if="!available" type="info" variant="tonal" class="mb-5">
        Open the ESPImageServer desktop app to install firmware over USB. If this is an older desktop window, restart it after updating the app.
      </v-alert>
      <p class="mb-5">Connect your display with a USB data cable. Close Arduino Serial Monitor and other apps using its COM port.</p>
      <v-row>
        <v-col cols="12" md="6">
          <v-select v-model="board" :items="boardItems" label="1. Physical display model" :disabled="!available || locked" hide-details="auto" @update:model-value="confirmed = false" />
        </v-col>
        <v-col cols="12" md="6">
          <v-select v-model="port" :items="ports" item-title="label" item-value="port" label="2. USB / COM port" :disabled="!available || locked" hide-details="auto" no-data-text="No serial ports found. Check your cable and driver, then refresh." @update:model-value="confirmed = false" />
          <v-btn variant="text" size="small" prepend-icon="mdi-refresh" class="mt-2" :disabled="!available || locked" @click="refreshPorts">Refresh ports</v-btn>
          <v-btn variant="text" size="small" prepend-icon="mdi-information-outline" class="mt-2" :disabled="!desktop?.identifyFirmware || locked || !port" @click="identify">Identify firmware</v-btn>
        </v-col>
      </v-row>
      <v-alert v-if="state.identityError" type="warning" variant="tonal" class="mt-4">{{ state.identityError }}</v-alert>
      <v-sheet v-if="state.identity" border rounded class="pa-4 mt-4" aria-live="polite">
        <div class="font-weight-bold">{{ state.identity.board_name }} · Firmware {{ state.identity.firmware_version }}</div>
        <div>{{ state.identity.port }} · Hardware ID {{ state.identity.hardware_id }} · {{ state.identity.width }} × {{ state.identity.height }}</div>
        <div>{{ state.identity.wifi_connected ? 'Wi-Fi connected' : state.identity.wifi_configured ? 'Wi-Fi saved, currently disconnected' : 'No saved Wi-Fi' }}</div>
        <div class="text-caption mt-2">Read directly from the running firmware over USB.</div>
      </v-sheet>
      <UsbWifiSetup v-if="state.identity" :identity="state.identity" :selected-port="port" :state="state.wifi" :locked="locked" @state="state = $event" />
      <v-btn class="my-4" variant="tonal" prepend-icon="mdi-folder-open-outline" :disabled="!available || locked" @click="choosePackage">3. Choose firmware folder</v-btn>
      <p class="text-body-2 text-medium-emphasis mb-4">Select the version folder containing manifest.json and the four binaries, for example JC4827W543 / 1.1.1.</p>
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
      <v-alert v-if="error || state.error" type="error" variant="tonal" class="mb-4">{{ error || state.error }}</v-alert>
      <div role="status" aria-live="polite" class="font-weight-medium mb-2">{{ stageLabel }}</div>
      <v-progress-linear v-if="state.busy && !wifiActive" indeterminate color="primary" rounded class="mb-4" aria-label="Firmware installation in progress" />
      <v-alert v-if="state.stage === 'written'" type="success" variant="tonal" class="mb-4">
        All four writes passed verification and a restart was requested. Check the physical screen for the expected board/version (and “No saved Wi-Fi” on an unconfigured board). Application startup has not been verified automatically.
      </v-alert>
      <v-alert v-if="state.stage === 'boot_verified'" type="success" variant="tonal" class="mb-4">
        All four writes passed verification. The running firmware now reports the expected board and version over USB.
      </v-alert>
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
.firmware-path { overflow-wrap: anywhere; }
.firmware-log { white-space: pre-wrap; overflow-wrap: anywhere; max-height: 300px; overflow: auto; font-size: 12px; padding: 12px; background: rgba(127,127,127,.08); border-radius: 6px; }
</style>
