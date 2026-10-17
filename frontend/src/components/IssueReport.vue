<script setup>
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { buildIssueReport, ISSUE_URL } from '../issueReport.js'

const props = defineProps({
  appVersion: String,
  imageModel: String,
  videoModel: String,
  display: Object,
  imageRotation: Number,
  videoRotation: Number,
  copyText: { type: Function, required: true },
})
const happened = ref('')
const steps = ref('')
const expected = ref('')
const includeLogs = ref(false)
const details = ref(null)
const loading = ref(false)
const loadError = ref('')
const copying = ref(false)
const copyStatus = ref('')
const copyError = ref('')
let requestVersion = 0
let controller

const report = computed(() => buildIssueReport({
  details: { ...details.value, app_version: details.value?.app_version || props.appVersion },
  happened: happened.value,
  steps: steps.value,
  expected: expected.value,
  imageModel: props.imageModel,
  videoModel: props.videoModel,
  display: props.display,
  imageRotation: props.imageRotation,
  videoRotation: props.videoRotation,
  includeLogs: includeLogs.value,
}))

async function loadDetails() {
  const version = ++requestVersion
  controller?.abort()
  const request = new AbortController()
  controller = request
  const timer = window.setTimeout(() => request.abort(), 15000)
  // Clear an older log excerpt immediately when refreshing or opting out.
  if (details.value) details.value = { ...details.value, logs: [] }
  loading.value = true
  loadError.value = ''
  try {
    const response = await fetch(`/diagnostics/report?include_logs=${includeLogs.value}`, {
      cache: 'no-store', signal: request.signal,
    })
    if (!response.ok) throw new Error(`Request failed (${response.status})`)
    const result = await response.json()
    if (!result || typeof result !== 'object' || Array.isArray(result)) throw new Error('Invalid report details')
    if (version === requestVersion) details.value = result
  } catch {
    if (version === requestVersion) loadError.value = 'System details could not be collected. Try Refresh details, or copy the report with the information already available.'
  } finally {
    window.clearTimeout(timer)
    if (version === requestVersion) loading.value = false
  }
}

async function copyReport() {
  if (loading.value || copying.value) return
  const text = report.value
  copying.value = true
  copyStatus.value = ''
  copyError.value = ''
  try {
    await props.copyText(text)
    copyStatus.value = text === report.value
      ? 'Issue report copied. Open GitHub and paste it into the issue description.'
      : 'The earlier report was copied. Copy again to include your latest changes.'
  } catch {
    copyError.value = 'Copy is unavailable. Expand Preview report and select the text to copy it manually.'
  } finally {
    copying.value = false
  }
}

watch(includeLogs, loadDetails)
watch(report, () => { copyStatus.value = ''; copyError.value = '' })
onMounted(loadDetails)
onUnmounted(() => { ++requestVersion; controller?.abort() })
</script>

<template>
  <section class="issue-report" aria-labelledby="issue-report-heading">
    <div class="d-flex align-center flex-wrap ga-2 mb-2">
      <h2 id="issue-report-heading" class="text-subtitle-1 font-weight-bold">Report a problem</h2>
      <v-spacer />
      <v-btn variant="text" size="small" prepend-icon="mdi-refresh" :loading="loading" :disabled="loading" @click="loadDetails">Refresh details</v-btn>
    </div>
    <p class="text-body-2 text-medium-emphasis mb-4">System, model, and display details are filled in automatically. Describe the problem, then copy the report into a GitHub issue.</p>
    <div class="issue-report__fields">
      <v-textarea v-model="happened" label="What happened?" placeholder="Describe the problem and any error you saw." variant="outlined" rows="2" auto-grow maxlength="4000" hide-details class="issue-report__happened" />
      <v-textarea v-model="steps" label="Steps to reproduce" placeholder="1. Open…&#10;2. Select…&#10;3. The problem appears." variant="outlined" rows="2" auto-grow maxlength="4000" hide-details />
      <v-textarea v-model="expected" label="What did you expect?" placeholder="Describe the result you expected." variant="outlined" rows="2" auto-grow maxlength="4000" hide-details />
    </div>
    <v-checkbox v-model="includeLogs" label="Include recent logs" density="compact" hide-details class="mt-2" />
    <p class="text-caption text-medium-emphasis mb-3">Known secrets and personal paths are redacted. Review the report before sharing.</p>
    <v-alert v-if="loadError" type="warning" variant="tonal" density="compact" class="mb-3" role="status">{{ loadError }}</v-alert>
    <v-expansion-panels variant="accordion" class="mb-4">
      <v-expansion-panel>
        <v-expansion-panel-title>Preview report</v-expansion-panel-title>
        <v-expansion-panel-text>
          <v-textarea :model-value="report" label="Issue report" readonly rows="12" hide-details variant="outlined" class="issue-report__preview" />
        </v-expansion-panel-text>
      </v-expansion-panel>
    </v-expansion-panels>
    <div class="d-flex flex-wrap ga-2">
      <v-btn color="primary" variant="tonal" prepend-icon="mdi-content-copy" :loading="copying" :disabled="loading || copying" @click="copyReport">Copy issue report</v-btn>
      <v-btn :href="ISSUE_URL" target="_blank" rel="noopener noreferrer" variant="text" append-icon="mdi-open-in-new">Open GitHub issue</v-btn>
    </div>
    <p v-if="copyStatus" class="text-body-2 text-success mt-3" role="status" aria-live="polite">{{ copyStatus }}</p>
    <p v-if="copyError" class="text-body-2 text-error mt-3" role="alert">{{ copyError }}</p>
  </section>
</template>

<style scoped>
.issue-report { padding: 20px; border: 1px solid rgba(var(--v-theme-primary), .25); border-radius: 12px; background: rgba(var(--v-theme-primary), .025); container-type: inline-size; }
.issue-report__fields { display: grid; grid-template-columns: minmax(0, 1fr); gap: 16px; }
.issue-report__fields > * { min-width: 0; }
.issue-report__preview :deep(textarea) { font: .8rem/1.6 Consolas, 'Cascadia Code', monospace; }
@container (min-width: 700px) {
  .issue-report__fields { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .issue-report__happened { grid-column: 1 / -1; }
}
</style>
