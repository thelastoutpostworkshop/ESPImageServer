<script setup>
import { computed, onUnmounted, ref, watch } from 'vue'
import { matchSetupDisplay } from '../setupConnection.js'

const props = defineProps({ identity: Object, selectedPort: String, locked: Boolean })
const emit = defineEmits(['ready', 'open-display'])
const found = ref(null), serverError = ref(false), elapsed = ref(0)
const eligible = computed(() => props.identity?.port === props.selectedPort && props.identity?.wifi_connected && !props.locked)
let timer, abort, generation = 0, since = 0
function stop() {
  generation++; clearTimeout(timer); abort?.abort(); found.value = null; emit('ready', false)
}
function restart() {
  stop(); elapsed.value = 0; serverError.value = false
  if (!eligible.value) return
  since = Date.now()
  void check(generation)
}
async function check(token) {
  const identity = { ...props.identity }
  const controller = new AbortController()
  abort = controller
  const timeout = setTimeout(() => controller.abort(), 4000)
  try {
    const response = await fetch('/displays', { cache: 'no-store', signal: controller.signal })
    if (!response.ok) throw new Error('Server unavailable')
    const displays = await response.json()
    if (token !== generation) return
    found.value = matchSetupDisplay(identity, displays, since)
    serverError.value = false
    emit('ready', Boolean(found.value))
  } catch {
    if (token !== generation) return
    found.value = null; serverError.value = true; emit('ready', false)
  } finally {
    clearTimeout(timeout)
    if (token === generation) {
      elapsed.value = Math.floor((Date.now() - since) / 1000)
      timer = setTimeout(() => check(token), 2000)
    }
  }
}
watch([() => props.identity?.hardware_id, () => props.identity?.firmware_version,
  () => props.selectedPort, () => Boolean(eligible.value)], restart, { immediate: true })
onUnmounted(stop)
</script>

<template>
  <v-sheet border rounded class="pa-4 mt-4">
    <h3 class="text-subtitle-1 font-weight-bold mb-2">4. Find this display on the server</h3>
    <div v-if="!eligible" role="status">{{ locked ? 'Finish the current USB operation to check the server connection.' : 'Connect to Wi-Fi, then refresh the USB identity to check the server connection.' }}</div>
    <template v-else>
      <v-alert v-if="found" type="success" variant="tonal" role="status">
        <strong>Ready — {{ found.name }}</strong><br>
        Wi-Fi connected. ESPImageServer has received recent contact from this exact USB board.
        <div class="text-caption mt-1">Hardware ID {{ identity.hardware_id }} · Firmware {{ identity.firmware_version }}</div>
        <v-btn class="mt-3" variant="tonal" @click="emit('open-display', found.id)">Use this display</v-btn>
      </v-alert>
      <template v-else>
        <div role="status">Wi-Fi connected and saved. {{ serverError ? 'The local server is not responding.' : 'Waiting for this display to contact ESPImageServer…' }}</div>
        <v-progress-linear v-if="elapsed < 90 && !serverError" indeterminate class="my-3" aria-label="Checking server connection" />
        <p class="mt-3 text-body-2">Keep the desktop app running. The board retries automatically; you do not need to enter the Wi-Fi password again.</p>
        <p v-if="elapsed >= 15 || serverError" class="mt-3 text-body-2">Check that the computer and display are on the same local network. Guest-network isolation, VPN routing, blocked mDNS, or the computer's firewall can prevent discovery. The default server address is http://espimageserver.local:8000. Check the board's configured server address if it was customized.</p>
        <v-btn class="mt-3" variant="text" @click="restart">Check server again</v-btn>
      </template>
    </template>
  </v-sheet>
</template>
