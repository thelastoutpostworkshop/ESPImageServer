<script setup>
defineProps({
  kind: { type: String, default: 'image', validator: value => ['image', 'video'].includes(value) },
  label: { type: String, required: true },
})
</script>

<template>
  <v-tooltip :text="label" location="bottom">
    <template #activator="{ props: tooltipProps }">
      <span
        v-bind="tooltipProps"
        class="generation-nav-indicator"
        role="img"
        :aria-label="label"
        tabindex="0"
      >
        <svg viewBox="0 0 28 28" aria-hidden="true" focusable="false">
          <circle class="generation-track" cx="14" cy="14" r="10.5" />
          <circle class="generation-ring" cx="14" cy="14" r="10.5" />
          <g v-if="kind === 'image'">
            <rect class="generation-image-outline" x="8" y="9" width="12" height="10" rx="1.5" />
            <path class="generation-image-outline" d="m8.7 17 3-3 2.6 2.6 2-2 3 3" />
            <circle cx="11.5" cy="12" r="1" fill="currentColor" />
          </g>
          <path v-else class="generation-video-play" d="M11.5 9.5 18 14l-6.5 4.5Z" />
        </svg>
      </span>
    </template>
  </v-tooltip>
</template>

<style scoped>
.generation-nav-indicator {
  display: inline-flex;
  flex: 0 0 26px;
  width: 26px;
  height: 26px;
  align-items: center;
  justify-content: center;
  color: rgb(var(--v-theme-primary));
  border-radius: 4px;
}

.generation-nav-indicator:focus-visible {
  outline: 2px solid currentColor;
  outline-offset: 3px;
}

.generation-nav-indicator svg { display: block; width: 100%; height: 100%; overflow: visible; }
.generation-image-outline { fill: none; stroke: currentColor; stroke-width: 1.3; stroke-linecap: round; stroke-linejoin: round; }
.generation-track { fill: none; stroke: currentColor; stroke-width: 2; opacity: .22; }
.generation-ring { fill: none; stroke: currentColor; stroke-width: 2; stroke-linecap: round; stroke-dasharray: 16 17; transform-origin: 14px 14px; animation: generation-turn 3s linear infinite; }
.generation-video-play { fill: currentColor; stroke: currentColor; stroke-width: 1; stroke-linejoin: round; }

@keyframes generation-turn {
  to { transform: rotate(360deg); }
}

@media (prefers-reduced-motion: reduce) {
  .generation-ring { animation: none; }
}
</style>
