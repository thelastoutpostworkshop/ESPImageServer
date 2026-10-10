<script setup>
import { computed } from 'vue'
import { renderReleaseNotes } from '../releaseNotes.js'
const props = defineProps({ release: Object, embedded: Boolean })
const notes = computed(() => props.release?.notes?.trim() || '')
const rendered = computed(() => renderReleaseNotes(notes.value))
const releaseUrl = computed(() => /^\d+\.\d+\.\d+$/.test(props.release?.version || '')
  ? `https://github.com/thelastoutpostworkshop/ESPImageFirmware/releases/tag/v${props.release.version}` : '')
</script>

<template>
  <section v-if="notes" class="firmware-release-notes" :class="embedded ? 'firmware-release-notes--embedded' : 'pa-4 mb-4'" aria-label="Firmware release notes">
    <h3 class="text-subtitle-1 font-weight-bold mb-3">What's new in {{ release.version }}</h3>
    <div class="release-markdown" v-html="rendered" />
    <a v-if="releaseUrl" :href="releaseUrl" target="_blank" rel="noopener noreferrer" class="release-link mt-4">View release on GitHub <v-icon icon="mdi-open-in-new" size="14" /></a>
  </section>
</template>

<style scoped>
.firmware-release-notes { border: 1px solid rgba(var(--v-theme-primary), .25); border-radius: 8px; background: rgba(var(--v-theme-primary), .05); min-width: 0; }
.firmware-release-notes--embedded { border: 0; background: none; }
.release-markdown { overflow-wrap: anywhere; line-height: 1.65; overflow-x: auto; }
.release-markdown :deep(p), .release-markdown :deep(ul), .release-markdown :deep(ol), .release-markdown :deep(pre), .release-markdown :deep(table) { margin-bottom: 12px; }
.release-markdown :deep(ul), .release-markdown :deep(ol) { padding-left: 24px; }
.release-markdown :deep(h1), .release-markdown :deep(h2), .release-markdown :deep(h3) { font-size: 1rem; margin: 16px 0 8px; }
.release-markdown :deep(pre) { white-space: pre-wrap; }
.release-markdown :deep(th), .release-markdown :deep(td) { padding: 6px 12px; border-bottom: 1px solid rgba(var(--v-theme-on-surface), .15); text-align: left; }
.release-markdown :deep(a), .release-link { color: rgb(var(--v-theme-primary)); }
.release-link { display: inline-block; font-size: .875rem; }
</style>
