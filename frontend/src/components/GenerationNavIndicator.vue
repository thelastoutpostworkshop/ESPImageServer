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
        <svg v-if="kind === 'image'" viewBox="0 0 28 28" aria-hidden="true" focusable="false">
          <path class="generation-image-outline" d="M18 8H4a1.5 1.5 0 0 0-1.5 1.5v14A1.5 1.5 0 0 0 4 25h15a1.5 1.5 0 0 0 1.5-1.5V16" />
          <path class="generation-image-outline" d="m3 21 5-5 4 4 3-3 5 5" />
          <circle cx="8" cy="12.5" r="1.5" fill="currentColor" />
          <path class="generation-sparkle generation-sparkle-large" d="m21 2 1.6 4.4L27 8l-4.4 1.6L21 14l-1.6-4.4L15 8l4.4-1.6Z" />
          <path class="generation-sparkle generation-sparkle-small" d="m25 15 .8 2.2L28 18l-2.2.8L25 21l-.8-2.2L22 18l2.2-.8Z" />
        </svg>
        <svg v-else viewBox="0 0 28 28" aria-hidden="true" focusable="false">
          <circle class="generation-video-track" cx="14" cy="14" r="10.5" />
          <circle class="generation-video-ring" cx="14" cy="14" r="10.5" />
          <path class="generation-video-play" d="M11.5 9.5 18 14l-6.5 4.5Z" />
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
.generation-image-outline { fill: none; stroke: currentColor; stroke-width: 1.7; stroke-linecap: round; stroke-linejoin: round; }
.generation-sparkle { fill: currentColor; transform-box: fill-box; transform-origin: center; animation: generation-sparkle-twinkle 2.6s ease-in-out infinite; }
.generation-sparkle-small { animation-delay: -.9s; }
.generation-video-track { fill: none; stroke: currentColor; stroke-width: 2; opacity: .22; }
.generation-video-ring { fill: none; stroke: currentColor; stroke-width: 2; stroke-linecap: round; stroke-dasharray: 16 17; transform-origin: 14px 14px; animation: generation-video-turn 3s linear infinite; }
.generation-video-play { fill: currentColor; stroke: currentColor; stroke-width: 1; stroke-linejoin: round; }

@keyframes generation-sparkle-twinkle {
  0%, 100% { opacity: .6; transform: scale(.8); }
  50% { opacity: 1; transform: scale(1); }
}

@keyframes generation-video-turn {
  to { transform: rotate(360deg); }
}

@media (prefers-reduced-motion: reduce) {
  .generation-sparkle, .generation-video-ring { animation: none; }
}
</style>
