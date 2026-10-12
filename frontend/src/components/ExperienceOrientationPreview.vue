<script setup>
import { computed, useId } from 'vue'
import BoardThumbnail from './BoardThumbnail.vue'
import { experienceOrientationGeometry } from '../displayExperience.js'

const props = defineProps({ display: Object, rotation: Number, video: Boolean })
const geometry = computed(() => experienceOrientationGeometry(props.display, props.rotation))
const gradientId = `${useId()}-experience-sky`
const boardStyle = computed(() => ({
  width: `${geometry.value.nativeWidth + 24}px`,
  height: `${geometry.value.nativeHeight + 24}px`,
  transform: `rotate(${geometry.value.boardRotation}deg)`,
}))
const screenStyle = computed(() => ({ width: `${geometry.value.nativeWidth}px`, height: `${geometry.value.nativeHeight}px` }))
const artworkStyle = computed(() => ({
  width: `${geometry.value.artworkWidth}px`, height: `${geometry.value.artworkHeight}px`,
  transform: `translate(-50%, -50%) rotate(${geometry.value.rotation}deg)`,
}))
</script>

<template>
  <figure class="experience-preview" :aria-label="`${display?.name || 'Display'}: ${geometry.shape}, ${geometry.rotation} degrees. The top marker shows the board orientation.`">
    <div class="experience-preview__stage" aria-hidden="true">
      <div class="experience-preview__board" :class="{ 'experience-preview__board--round': geometry.round }" :style="boardStyle">
        <span class="experience-preview__top">TOP</span>
        <span class="experience-preview__port" />
        <div class="experience-preview__screen" :style="screenStyle">
          <div class="experience-preview__artwork" :style="artworkStyle">
            <svg viewBox="0 0 240 200" preserveAspectRatio="xMidYMid slice">
              <defs><linearGradient :id="gradientId" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#13395c" /><stop offset="1" stop-color="#70d5db" /></linearGradient></defs>
              <rect width="240" height="200" :fill="`url(#${gradientId})`" />
              <circle cx="180" cy="60" r="25" fill="#ffd166" />
              <path d="M0 158 70 67 132 154 172 105 240 172V200H0Z" fill="#347d98" />
              <path d="m49 94 21-27 23 33-24-10Z" fill="#e2f5f3" />
              <path d="M0 170 78 126 137 179 196 144 240 176V200H0Z" fill="#15516a" />
              <path d="M0 184Q66 171 126 191T240 182V200H0Z" fill="#0d354a" />
            </svg>
            <span class="experience-preview__up"><v-icon size="15">mdi-arrow-up</v-icon> UP</span>
            <span v-if="video" class="experience-preview__play"><v-icon size="24">mdi-play</v-icon></span>
          </div>
        </div>
      </div>
    </div>
    <figcaption>
      <div class="d-flex align-center justify-center ga-2 mb-1"><BoardThumbnail :board-target="display?.board_target" :size="32" /><strong>{{ display?.name || 'Active display' }}</strong></div>
      <div>{{ geometry.shape }} · {{ geometry.rotation }}° · {{ geometry.width }} × {{ geometry.height }}</div>
      <div class="text-caption text-medium-emphasis mt-1">Example {{ video ? 'video' : 'image' }} · TOP marks the board’s normal top edge.</div>
    </figcaption>
  </figure>
</template>

<style scoped>
.experience-preview { margin: 0; text-align: center; }
.experience-preview__stage { display: grid; width: 100%; min-width: 248px; height: 248px; place-items: center; }
.experience-preview__board { position: relative; display: grid; place-items: center; box-sizing: border-box; border: 1px solid rgba(var(--v-theme-primary), .55); border-radius: 12px; background: #152c39; box-shadow: 0 12px 28px #0003; transition: transform .35s ease; }
.experience-preview__screen { position: relative; overflow: hidden; border-radius: 5px; outline: 2px solid #081721; }
.experience-preview__artwork { position: absolute; left: 50%; top: 50%; transform-origin: center; }
.experience-preview__artwork svg { display: block; width: 100%; height: 100%; }
.experience-preview__top { position: absolute; left: 50%; top: -10px; transform: translateX(-50%); padding: 1px 7px; border-radius: 4px; font-size: 9px; font-weight: 800; letter-spacing: 1px; color: #fff; background: #147caf; }
.experience-preview__port { position: absolute; left: 50%; bottom: -4px; width: 20px; height: 8px; transform: translateX(-50%); border: 2px solid #8297a3; border-radius: 3px; background: #07121a; }
.experience-preview__up { position: absolute; top: 8px; left: 50%; display: flex; align-items: center; gap: 2px; transform: translateX(-50%); padding: 2px 7px; border-radius: 20px; color: #fff; background: #0b293f99; font-size: 10px; font-weight: 700; }
.experience-preview__play { position: absolute; top: 50%; left: 50%; display: grid; width: 42px; height: 42px; place-items: center; transform: translate(-50%, -50%); border: 1px solid #ffffff80; border-radius: 50%; color: #fff; background: #102b4780; }
.experience-preview__board--round { border-radius: 50%; }
.experience-preview__board--round .experience-preview__screen { border-radius: 50%; }
@media (prefers-reduced-motion: reduce) { .experience-preview__board { transition: none; } }
</style>
