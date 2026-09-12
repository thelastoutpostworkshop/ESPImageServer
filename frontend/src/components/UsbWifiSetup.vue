<script setup>
import { computed, onUnmounted, ref, watch } from 'vue'

const props = defineProps({ identity: Object, selectedPort: String, state: Object, locked: Boolean })
const emit = defineEmits(['state', 'editing'])
const desktop = window.espImageServerDesktop
const ssid = ref(''), password = ref(''), auth = ref('personal'), error = ref('')
const showPassword = ref(false)
const editing = ref(false), forgetDialog = ref(false)
watch(editing, value => emit('editing', value))
const pending = ref(false)
const supported = computed(() => desktop?.startWifiSetup && props.identity?.capabilities?.includes('wifi_connect'))
const matches = computed(() => props.identity?.port === props.selectedPort)
const canForget = computed(() => props.identity?.capabilities?.includes('wifi_forget'))
const wifi = computed(() => props.state?.hardwareId === props.identity?.hardware_id && props.state?.port === props.selectedPort ? props.state : null)
const active = computed(() => ['opening', 'scanning', 'connecting', 'obtaining_ip'].includes(wifi.value?.stage))
const disabled = computed(() => !supported.value || !matches.value || props.locked || pending.value)
const label = computed(() => ({ opening: 'Opening USB connection', scanning: 'Scanning for networks',
  scan_complete: 'Scan complete', connecting: 'Connecting to Wi-Fi', obtaining_ip: 'Obtaining an IP address',
  connected: 'Wi-Fi connected and saved', cancelled: 'Setup cancelled; previous settings retained',
  forgotten: 'Saved Wi-Fi removed. Choose a network to set up this board again.',
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
  if (disabled.value) return
  if (action === 'forget' && (!forgetDialog.value || !canForget.value)) return
  pending.value = true; error.value = ''
  try {
    const payload = { action, port: props.selectedPort, hardwareId: props.identity.hardware_id }
    if (action === 'connect') Object.assign(payload, { ssid: ssid.value, password: password.value, auth: auth.value })
    if (action === 'forget') { payload.confirm = true; forgetDialog.value = false }
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
// IPC polling replaces identity objects. Compare the two device identifiers
// separately so an unchanged snapshot does not clear a form being edited.
watch([() => props.identity?.hardware_id, () => props.selectedPort], () => {
  password.value = ''; ssid.value = ''; error.value = ''; network.value = null
  editing.value = false; forgetDialog.value = false; showPassword.value = false
})
watch(() => wifi.value?.stage, stage => {
  if (stage === 'connected' || stage === 'forgotten') {
    editing.value = false; password.value = ''; ssid.value = ''; network.value = null
  }
})
watch(auth, () => { password.value = '' })
watch(password, value => { if (!value) showPassword.value = false })
onUnmounted(() => {
  password.value = ''
  if (active.value || pending.value) void desktop?.cancelWifiSetup().catch(() => {})
})
</script>

<template>
  <v-sheet border rounded class="pa-4 mt-4">
    <h2 class="text-h6 mb-2">{{ identity?.wifi_configured ? 'Manage Wi-Fi' : 'Connect to Wi-Fi' }}</h2>
    <v-alert v-if="!supported" type="info" variant="tonal">Install firmware 1.1.3 or later with USB Wi-Fi setup, then identify it. An updated desktop app is also required.</v-alert>
    <v-alert v-else-if="!matches" type="info" variant="tonal">Identify the selected USB port before configuring Wi-Fi.</v-alert>
    <template v-else>
      <v-alert v-if="identity.wifi_configured && !editing" type="info" variant="tonal" class="mb-3">
        {{ identity.wifi_connected ? 'Wi-Fi is connected. You can keep this network or change it below.' : 'Your Wi-Fi settings are saved. Checking whether the board has reconnected…' }}
      </v-alert>
      <div v-if="identity.wifi_configured" class="d-flex flex-wrap ga-2 mb-3">
        <v-btn variant="tonal" :disabled="disabled" @click="editing = !editing; password = ''">{{ editing ? 'Keep current Wi-Fi' : 'Change Wi-Fi' }}</v-btn>
        <v-btn variant="text" color="warning" :disabled="disabled || !canForget" @click="forgetDialog = true">Forget Wi-Fi…</v-btn>
      </div>
      <p v-if="identity.wifi_configured && !canForget" class="text-caption mb-3">Changing Wi-Fi works with this firmware. Upgrade to firmware 1.1.4 or later to forget it over USB.</p>
      <template v-if="!identity.wifi_configured || editing">
      <p class="text-body-2 mb-3">Choose your 2.4 GHz home network, or enter its name below.</p>
      <p class="text-body-2 mb-3">Scanning briefly disconnects Wi-Fi. The board saves new credentials only after obtaining an IP address and restores previous settings if setup fails or is cancelled.</p>
      <v-btn variant="tonal" prepend-icon="mdi-wifi" :disabled="disabled" @click="start('scan')">Scan networks</v-btn>
      <v-select v-if="networks.length" v-model="network" :items="networks" label="Available networks (up to 20)" class="mt-4" :disabled="disabled" @update:model-value="chooseNetwork" />
      <p v-if="wifi?.stage === 'scan_complete' && !networks.length" class="mt-3">No networks found. Retry nearby or enter a hidden network below.</p>
      <v-text-field v-model="ssid" label="Network name" hint="You can also enter a hidden network." :disabled="disabled" class="mt-4" autocomplete="off" />
      <v-select v-model="auth" label="Network security" :items="[{ title: 'WPA2 Personal', value: 'personal' }, { title: 'Open (no password)', value: 'open' }]" :disabled="disabled" />
      <v-text-field v-if="auth === 'personal'" v-model="password" label="Wi-Fi password" :type="showPassword ? 'text' : 'password'" autocomplete="new-password" :disabled="disabled" hint="Saved only on your display." persistent-hint>
        <template #append-inner>
          <v-btn variant="text" size="small" :prepend-icon="showPassword ? 'mdi-eye-off-outline' : 'mdi-eye-outline'" :aria-label="showPassword ? 'Hide Wi-Fi password' : 'Show Wi-Fi password'" :aria-pressed="showPassword" :disabled="disabled" @click="showPassword = !showPassword">{{ showPassword ? 'Hide' : 'Show' }}</v-btn>
        </template>
      </v-text-field>
      <div class="d-flex ga-2 my-3">
        <v-btn color="primary" :disabled="disabled || !ssid || (auth === 'personal' && !password)" @click="start('connect')">{{ wifi?.stage === 'failed' ? 'Retry connection' : 'Connect and save' }}</v-btn>
        <v-btn v-if="active" variant="text" @click="cancel">Cancel</v-btn>
      </div>
      </template>
      <div v-if="wifi" role="status" aria-live="polite">{{ label }}</div>
      <v-progress-linear v-if="active" indeterminate class="my-3" aria-label="Wi-Fi setup in progress" />
      <v-alert v-if="error || wifi?.error" type="error" variant="tonal" class="mt-3">{{ error || wifi?.error }}</v-alert>
      <v-alert v-if="wifi?.stage === 'connected'" type="success" variant="tonal" class="mt-3">Wi-Fi credentials saved on the board. IP address: {{ wifi.ip }}. The board will reconnect after reboot. Server discovery is separate from this USB confirmation.</v-alert>
    </template>
    <v-dialog v-model="forgetDialog" max-width="480" :persistent="pending">
      <v-card title="Forget Wi-Fi on this display?">
        <v-card-text>
          <p>{{ identity?.board_name }} · {{ selectedPort }}</p>
          <p class="text-caption mb-3">Hardware ID {{ identity?.hardware_id }}</p>
          <p>This disconnects this board and removes its saved Wi-Fi credentials. SD-card files and other display settings are preserved. You can set up a new network over USB afterward.</p>
        </v-card-text>
        <v-card-actions>
          <v-btn :disabled="pending" @click="forgetDialog = false">Keep Wi-Fi</v-btn>
          <v-btn color="warning" :disabled="disabled || !canForget" @click="start('forget')">Forget Wi-Fi</v-btn>
        </v-card-actions>
      </v-card>
    </v-dialog>
  </v-sheet>
</template>
