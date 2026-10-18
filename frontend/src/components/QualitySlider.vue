<script setup>
defineProps({
  id: { type: String, required: true },
  label: { type: String, required: true },
  modelValue: { type: Number, required: true },
  description: { type: String, required: true },
})
defineEmits(['update:modelValue'])
</script>

<template>
  <div class="quality-control">
    <div class="quality-control__heading">
      <h3 class="text-subtitle-1 font-weight-bold">{{ label }}</h3>
      <span class="quality-control__value">{{ modelValue }} <span class="text-medium-emphasis">/ 10</span></span>
    </div>
    <v-slider
      :id="id"
      :model-value="modelValue"
      :aria-label="label"
      :aria-describedby="`${id}-range ${id}-description`"
      :min="1"
      :max="10"
      :step="1"
      thumb-label
      thumb-color="#1565c0"
      show-ticks="always"
      color="primary"
      hide-details
      class="quality-control__slider"
      @update:model-value="$emit('update:modelValue', $event)"
    />
    <div :id="`${id}-range`" class="quality-control__range">
      <div><strong>Lowest quality</strong><span>Smaller files</span></div>
      <div><strong>Highest quality</strong><span>Larger files</span></div>
    </div>
    <p :id="`${id}-description`" class="text-body-2 text-medium-emphasis mt-4">{{ description }}</p>
    <slot />
  </div>
</template>

<style scoped>
.quality-control { min-width: 0; padding: 20px; border: 1px solid rgba(var(--v-theme-on-surface), 0.14); border-radius: 12px; }
.quality-control__heading { display: flex; align-items: center; justify-content: space-between; gap: 12px; }
.quality-control__value { flex-shrink: 0; padding: 4px 10px; border-radius: 8px; background: rgba(var(--v-theme-primary), 0.1); font-size: 1rem; font-weight: 700; font-variant-numeric: tabular-nums; }
.quality-control__slider { margin: 16px 0 0; }
.quality-control__range { display: flex; justify-content: space-between; gap: 16px; font-size: 0.75rem; }
.quality-control__range > div { display: flex; flex-direction: column; gap: 2px; }
.quality-control__range > div:last-child { text-align: right; }
.quality-control__range span { color: rgba(var(--v-theme-on-surface), 0.7); }
</style>
