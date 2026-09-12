<script setup>
import { computed, onUnmounted, ref, watch } from 'vue'

const props = defineProps({ identity: Object, selectedPort: String, state: Object, locked: Boolean })
const emit = defineEmits(['state'])
const desktop = window.espImageServerDesktop
const ssid = ref(''), password = ref(''), auth = ref('personal'), error = ref('')
const pending = ref(false)
const supported = computed(() => desktop?.startWifiSetup && props.identity?.capabilities?.includes('wifi_connect'))
const matches = computed(() => props.identity?.port === props.selectedPort)
const wifi = computed(() => props.state?.hardwareId === props.identity?.hardware_id && props.state?.port === props.selectedPort ? props.state : null)
const active = computed(() => ['opening', 'scanning', 'connecting', 'obtaining_ip'].includes(wifi.value?.stage))
const disabled = computed(() => !supported.value || !matches.value || props.locked || pending.value)
const label = computed(() => ({ opening: 'Opening USB connection', scanning: 'Scanning for networks',
  scan_complete: 'Scan complete', connecting: 'Connecting to Wi-Fi', obtaining_ip: 'Obtaining an IP address',
  connected: 'Wi-Fi connected and saved', cancelled: 'Setup cancelled; previous settings retained',
  failed: 'Wi-Fi setup needs attention' }[wifi.value?.stage] || 'Connect this display to Wi-Fi'))
const networks = computed(() => (wifi.value?.networks || []).map((n, index) => ({
  title: `${n.ssid} · ${n.rssi} dBm · ${n.auth === 'open' ? 'Open' : n.auth === 'personal' ? 'WPA2 Personal' : 'Unsupported security'}`,
  value: index, props: { disabled: n.auth === 'unsupported' }
})))
const network = ref(null)
function chooseNetwork(index) {
  const n = wifi.value?.networks?.[index]
  if (n) { ssid.value = n.ssid; auth.value = n.auth; password.value = '' }
}
async function start(action) {
  pending.value = true; error.value = ''
  try {
    const payload = { action, port: props.selectedPort, hardwareId: props.identity.hardware_id }
    if (action === 'connect') Object.assign(payload, { ssid: ssid.value, password: password.value, auth: auth.value })
    // IPC is invoked before clearing the field; nothing is persisted locally.
    const operation = desktop.startWifiSetup(payload)
    password.value = ''; payload.password = ''
    const result = await operation
    if (!result.ok) throw new Error(result.error)
    emit('state', result.value)
  } catch (e) { error.value = e.message }
  finally { pending.value = false }
}
async function cancel() {
  password.value = ''; error.value = ''
  try { const result = await desktop.cancelWifiSetup(); if (!result.ok) throw new Error(result.error) }
  catch (e) { error.value = e.message }
}
watch(() => [props.identity?.hardware_id, props.selectedPort], () => {
  password.value = ''; ssid.value = ''; error.value = ''; network.value = null
})
watch(auth, () => { password.value = '' })
onUnmounted(() => {
  password.value = ''
  if (active.value || pending.value) void desktop?.cancelWifiSetup().catch(() => {})
})
</script>

<template>
  <v-sheet border rounded class="pa-4 mt-4">
    <h3 class="text-subtitle-1 font-weight-bold mb-2">Wi-Fi setup over USB</h3>
    <v-alert v-if="!supported" type="info" variant="tonal">Install firmware 1.1.3 or later with USB Wi-Fi setup, then identify it. An updated desktop app is also required.</v-alert>
    <v-alert v-else-if="!matches" type="info" variant="tonal">Identify the selected USB port before configuring Wi-Fi.</v-alert>
    <template v-else>
      <p class="text-body-2 mb-3">Use a 2.4 GHz network with WPA2 Personal (including mixed WPA2/WPA3) or no password. Enterprise, WEP, WPA-only, and WPA3-only networks are not supported by this setup flow.</p>
      <p class="text-body-2 mb-3">Scanning briefly disconnects Wi-Fi. The board saves new credentials only after obtaining an IP address and restores previous settings if setup fails or is cancelled.</p>
      <v-btn variant="tonal" prepend-icon="mdi-wifi" :disabled="disabled" @click="start('scan')">Scan networks</v-btn>
      <v-select v-if="networks.length" v-model="network" :items="networks" label="Available networks (up to 20)" class="mt-4" :disabled="disabled" @update:model-value="chooseNetwork" />
      <p v-if="wifi?.stage === 'scan_complete' && !networks.length" class="mt-3">No networks found. Retry nearby or enter a hidden network below.</p>
      <v-text-field v-model="ssid" label="Network name (SSID)" hint="You can enter a hidden network manually. Maximum 32 UTF-8 bytes." persistent-hint :disabled="disabled" class="mt-4" autocomplete="off" />
      <v-select v-model="auth" label="Network security" :items="[{ title: 'WPA2 Personal', value: 'personal' }, { title: 'Open (no password)', value: 'open' }]" :disabled="disabled" />
      <v-text-field v-if="auth === 'personal'" v-model="password" label="Wi-Fi password" type="password" autocomplete="new-password" :disabled="disabled" hint="8–63 printable ASCII characters, or a 64-digit hexadecimal key. Sent only over USB; not saved by the desktop app." persistent-hint />
      <div class="d-flex ga-2 my-3">
        <v-btn color="primary" :disabled="disabled || !ssid || (auth === 'personal' && !password)" @click="start('connect')">{{ wifi?.stage === 'failed' ? 'Retry connection' : 'Connect and save' }}</v-btn>
        <v-btn v-if="active" variant="text" @click="cancel">Cancel</v-btn>
      </div>
      <div role="status" aria-live="polite">{{ label }}</div>
      <v-progress-linear v-if="active" indeterminate class="my-3" aria-label="Wi-Fi setup in progress" />
      <v-alert v-if="error || wifi?.error" type="error" variant="tonal" class="mt-3">{{ error || wifi?.error }}</v-alert>
      <v-alert v-if="wifi?.stage === 'connected'" type="success" variant="tonal" class="mt-3">Wi-Fi credentials saved on the board. IP address: {{ wifi.ip }}. The board will reconnect after reboot. Server discovery is separate from this USB confirmation.</v-alert>
    </template>
  </v-sheet>
</template>
