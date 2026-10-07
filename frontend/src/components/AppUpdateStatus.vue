<script setup>
import { computed } from 'vue'
import { appUpdateInstallerLabel, useAppUpdates } from '../composables/useAppUpdates.js'

const props = defineProps({ currentVersion: String })
const { result, checking, checkingManually, automaticEnabled, statusMessage, checkManually } = useAppUpdates()
const installedVersion = computed(() => result.value?.installed_version || props.currentVersion)
const checkedAt = computed(() => {
  if (!result.value?.checked_at) return ''
  const date = new Date(result.value.checked_at)
  return Number.isNaN(date.getTime()) ? '' : date.toLocaleString()
})
const statusColor = computed(() => ['error', 'unavailable'].includes(result.value?.status) ? 'warning' : result.value?.status === 'up_to_date' && result.value.checked_successfully && !result.value.stale ? 'success' : 'info')
</script>

<template>
  <section class="mt-6" aria-labelledby="app-update-heading">
    <div class="d-flex align-center flex-wrap ga-3">
      <h3 id="app-update-heading" class="text-subtitle-1 font-weight-bold">App updates</h3>
      <v-spacer />
      <v-btn variant="tonal" color="primary" prepend-icon="mdi-update" :loading="checkingManually" :disabled="checkingManually" @click="checkManually">Check for updates</v-btn>
    </div>
    <div v-if="installedVersion" class="text-body-2 text-medium-emphasis mt-2">Installed version: {{ installedVersion }}</div>
    <div class="text-caption text-medium-emphasis mt-2">GitHub is checked at most once every 24 hours. Manual checks use the cached result during that time.</div>
    <v-alert class="mt-3" :type="statusColor" variant="tonal" density="compact" role="status" aria-live="polite">
      {{ checking ? 'Checking for app updates…' : statusMessage }}
      <div v-if="result?.stale && result?.update_available" class="mt-1">Last known available release: {{ result.latest_version }}.</div>
    </v-alert>
    <div v-if="!automaticEnabled && result?.status !== 'disabled'" class="text-caption text-medium-emphasis mt-2">Automatic checks are off. Manual checking is still available.</div>
    <div v-if="checkedAt" class="text-caption text-medium-emphasis mt-2">Last successful check: {{ checkedAt }}</div>
    <div v-if="result?.update_available || result?.status === 'unsupported'" class="d-flex flex-wrap ga-2 mt-3">
      <v-btn v-if="result.update_available && result.download_url" variant="tonal" color="primary" :href="result.download_url" target="_blank" rel="noopener noreferrer">{{ appUpdateInstallerLabel(result.platform) }}</v-btn>
      <v-btn v-if="result.release_url" variant="text" :href="result.release_url" target="_blank" rel="noopener noreferrer">Release notes</v-btn>
      <v-btn v-if="result.update_available && result.checksum_url" variant="text" :href="result.checksum_url" target="_blank" rel="noopener noreferrer">Checksum file</v-btn>
    </div>
    <div v-if="result?.download_url && result?.update_available" class="text-caption text-medium-emphasis mt-2">The installer matches the computer running ESPImageServer. Download it, then run it to update the app.</div>
  </section>
</template>
