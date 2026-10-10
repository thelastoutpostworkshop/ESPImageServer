<script setup>
import { computed, ref, watch } from 'vue'
import { boardThumbnailSource } from '../boardThumbnail.js'

const props = defineProps({
  boardTarget: { type: String, default: '' },
  size: { type: Number, default: 48 },
})
const imageSource = computed(() => boardThumbnailSource(props.boardTarget))
const failedImageSource = ref('')
const showImage = computed(() => imageSource.value && imageSource.value !== failedImageSource.value)

watch(imageSource, () => { failedImageSource.value = '' })

function imageFailed(event) {
  failedImageSource.value = event.currentTarget.getAttribute('src')
}
</script>

<template>
  <span class="board-thumbnail" :style="{ width: `${size}px`, height: `${size}px` }" aria-hidden="true">
    <img v-if="showImage" :key="imageSource" :src="imageSource" alt="" class="board-thumbnail-image" @error="imageFailed" />
    <v-icon v-else :size="Math.round(size * .5)" class="text-medium-emphasis">mdi-monitor</v-icon>
  </span>
</template>

<style scoped>
.board-thumbnail {
  box-sizing: border-box;
  display: inline-flex;
  flex: 0 0 auto;
  align-items: center;
  justify-content: center;
  overflow: hidden;
  padding: 4px;
  border: 1px solid rgba(var(--v-theme-on-surface), .09);
  border-radius: 8px;
  background: rgba(var(--v-theme-on-surface), .045);
}
.board-thumbnail-image { display: block; width: 100%; height: 100%; object-fit: contain; }
</style>
