<script setup>
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'

const props = defineProps({ displays: { type: Array, default: () => [] }, enabled: Boolean })
defineEmits(['setup'])
const updates = ref([])
const dismissed = ref(new Set())
const canInstall = Boolean(window.espImageServerDesktop?.firmwareReleases)
const visible = computed(() => props.enabled ? updates.value.filter(update =>
  props.displays.some(display => display.id === update.display_id && display.board_target === update.board && display.online && display.firmware_version === update.installed_version) &&
  !dismissed.value.has(`${update.display_id}:${update.version}`)) : [])
let timer, controller

async function check() {
  controller?.abort()
  if (!props.enabled || !props.displays.some(display => display.online)) {
    updates.value = []
    return
  }
  const request = new AbortController()
  controller = request
  try {
    const response = await fetch('/firmware-updates', { signal: request.signal })
    if (!response.ok) return
    const result = await response.json()
    if (!request.signal.aborted) updates.value = result.enabled ? result.updates : []
  } catch { /* A failed check must not interrupt normal use. */ }
}

watch(() => `${props.enabled}:${props.displays.map(d => `${d.id}:${d.online}:${d.firmware_version}:${d.board_target}`).sort().join('|')}`, check)
onMounted(() => { check(); timer = window.setInterval(check, 60000) })
onUnmounted(() => { window.clearInterval(timer); controller?.abort() })
</script>

<template>
  <v-alert v-for="update in visible" :key="`${update.display_id}:${update.version}`"
    type="info" variant="tonal" class="mb-4" closable role="status"
    @click:close="dismissed.add(`${update.display_id}:${update.version}`)">
    <strong>New firmware available for {{ update.name }}</strong>
    <div>Version {{ update.version }} is available. Installed: {{ update.installed_version }}.</div>
    <div class="text-body-2 mt-1">Connect the board by USB to the desktop app to install the update.</div>
    <v-btn v-if="canInstall" class="mt-2 mr-2" variant="tonal" @click="$emit('setup')">Set up display</v-btn>
    <v-btn class="mt-2" variant="text" :href="update.release_url" target="_blank" rel="noopener noreferrer">Release notes</v-btn>
  </v-alert>
</template>
