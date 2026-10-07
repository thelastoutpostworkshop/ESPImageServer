<script setup>
import { onMounted, onUnmounted, watch } from 'vue'
import { appUpdateInstallerLabel, useAppUpdates } from '../composables/useAppUpdates.js'

const props = defineProps({ enabled: Boolean })
const updates = useAppUpdates()
const { visibleUpdate } = updates
let timer
watch(() => props.enabled, enabled => {
  updates.setAutomaticEnabled(enabled)
  if (enabled) void updates.checkAutomatically()
})
onMounted(() => {
  updates.setAutomaticEnabled(props.enabled)
  if (props.enabled) void updates.checkAutomatically()
  // The server caches checks and handles retry delays for the public feed.
  timer = window.setInterval(updates.checkAutomatically, 60_000)
})
onUnmounted(() => {
  window.clearInterval(timer)
  updates.setAutomaticEnabled(false)
})
</script>

<template>
  <v-alert v-if="visibleUpdate" type="info" variant="tonal" class="mb-4" closable role="status" aria-live="polite"
    @click:close="updates.dismissVersion(visibleUpdate.latest_version)">
    <strong>ESPImageServer {{ visibleUpdate.latest_version }} is available</strong>
    <div>Installed: {{ visibleUpdate.installed_version }}.</div>
    <div v-if="visibleUpdate.stale" class="text-body-2 mt-1">This is the last known release. The latest check could not be completed; try again from About.</div>
    <div v-if="!visibleUpdate.download_url" class="text-body-2 mt-1">There is no installer for the computer running ESPImageServer. Open the release notes for available platforms.</div>
    <v-btn v-if="visibleUpdate.download_url" class="mt-2 mr-2" variant="tonal" :href="visibleUpdate.download_url" target="_blank" rel="noopener noreferrer">{{ appUpdateInstallerLabel(visibleUpdate.platform) }}</v-btn>
    <v-btn v-if="visibleUpdate.release_url" class="mt-2" variant="text" :href="visibleUpdate.release_url" target="_blank" rel="noopener noreferrer">Release notes</v-btn>
  </v-alert>
</template>
