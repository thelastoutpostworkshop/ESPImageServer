<script setup>
import { computed, onUnmounted, ref, watch } from 'vue'
import { matchSetupDisplay } from '../setupConnection.js'

const props = defineProps({ identity: Object, selectedPort: String, locked: Boolean })
const emit = defineEmits(['ready', 'open-display'])
const found = ref(null), serverError = ref(false), elapsed = ref(0)
const testDialog = ref(false), images = ref([]), selectedImage = ref(null), imageBusy = ref(false), imageError = ref(''), imageStatus = ref('')
const eligible = computed(() => props.identity?.port === props.selectedPort && props.identity?.wifi_connected && !props.locked)
let timer, abort, generation = 0, since = 0
function stop() {
  generation++; clearTimeout(timer); abort?.abort(); found.value = null; emit('ready', false)
  testDialog.value = false; selectedImage.value = null; imageStatus.value = ''; imageError.value = ''
}
async function chooseTestImage() {
  if (!found.value || imageBusy.value) return
  const token = generation
  testDialog.value = true; imageBusy.value = true; imageError.value = ''; imageStatus.value = ''; images.value = []; selectedImage.value = null
  try {
    const response = await fetch('/saved-images')
    if (!response.ok) throw new Error('Could not load saved images. Try again.')
    const data = await response.json()
    if (token === generation) images.value = Array.isArray(data) ? data : []
  } catch (e) { if (token === generation) imageError.value = e.message }
  finally { imageBusy.value = false }
}
async function sendTestImage() {
  if (!found.value || !selectedImage.value || imageBusy.value || !testDialog.value) return
  const token = generation, displayId = found.value.id, imageId = selectedImage.value
  imageBusy.value = true; imageError.value = ''
  try {
    const response = await fetch(`/saved-images/${encodeURIComponent(imageId)}/display`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ display_ids: [displayId] })
    })
    if (!response.ok) throw new Error('Could not send the image. Check the display connection and try again.')
    if (token === generation) { imageStatus.value = 'Image queued for this display. Check its screen to confirm it appears.'; testDialog.value = false }
  } catch (e) { if (token === generation) imageError.value = e.message }
  finally { imageBusy.value = false }
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
    <h2 class="text-h6 mb-3">{{ found ? 'Your display is ready' : 'Connecting to ESPImageServer' }}</h2>
    <div v-if="!eligible" role="status">{{ locked ? 'Checking your display…' : 'Waiting for the Wi-Fi connection…' }}</div>
    <template v-else>
      <v-alert v-if="found" type="success" variant="tonal" role="status">
        <strong>{{ found.name }}</strong><br>
        Wi-Fi connected · Server connected
        <div class="d-flex flex-wrap ga-2 mt-4"><v-btn color="primary" :disabled="imageBusy" @click="chooseTestImage">Send a test image</v-btn><v-btn variant="text" @click="emit('open-display', found.id)">Open display</v-btn></div>
      </v-alert>
      <template v-else>
        <div role="status">Wi-Fi connected and saved. {{ serverError ? 'The local server is not responding.' : 'Waiting for this display to contact ESPImageServer…' }}</div>
        <v-progress-linear v-if="elapsed < 90 && !serverError" indeterminate class="my-3" aria-label="Checking server connection" />
        <p class="mt-3 text-body-2">Keep the desktop app running. The board retries automatically; you do not need to enter the Wi-Fi password again.</p>
        <details v-if="elapsed >= 15 || serverError" class="mt-3"><summary>Connection troubleshooting</summary><p class="mt-2 text-body-2">Check that the computer and display are on the same local network. Guest-network isolation, VPN routing, blocked mDNS, or the computer's firewall can prevent discovery. The default server address is http://espimageserver.local:8000. Check the board's configured server address if it was customized.</p></details>
        <v-btn class="mt-3" variant="text" @click="restart">Check server again</v-btn>
      </template>
    </template>
    <p v-if="imageStatus" role="status" class="mt-3">{{ imageStatus }}</p>
    <v-dialog v-model="testDialog" max-width="640" :persistent="imageBusy">
      <v-card title="Send a test image">
        <v-card-text>
          <p class="mb-4">Choose an existing image to show on {{ found?.name }}. This replaces what is currently displayed.</p>
          <v-progress-linear v-if="imageBusy" indeterminate class="mb-3" />
          <v-alert v-if="imageError" type="error" variant="tonal" class="mb-3">{{ imageError }}</v-alert>
          <p v-if="!imageBusy && !images.length && !imageError">There are no saved images yet. Create and save an image in Generate image, then return here to test it.</p>
          <v-select v-if="images.length" v-model="selectedImage" :items="images.map(img => ({title: img.metadata?.prompt || img.filename, value: img.id}))" label="Saved image" :disabled="imageBusy || !found" />
          <img v-if="selectedImage" :src="`/saved-images/${encodeURIComponent(selectedImage)}/thumbnail`" alt="Selected test image" style="display:block;max-width:100%;max-height:240px;margin:auto">
        </v-card-text>
        <v-card-actions><v-btn :disabled="imageBusy" @click="testDialog = false">Cancel</v-btn><v-btn color="primary" :disabled="imageBusy || !found || !selectedImage" @click="sendTestImage">Send to this display</v-btn></v-card-actions>
      </v-card>
    </v-dialog>
  </v-sheet>
</template>
