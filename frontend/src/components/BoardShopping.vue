<script setup>
import { computed, ref, watch } from 'vue'

defineProps({ compact: Boolean })
const open = ref(false)
const dialogEntered = ref(false)
const readyImages = ref(new Set())
// Purchase links supplied by video_conversion/src/config/boardPresets.ts.
const boards = [
  { target: 'JC4827W543', name: 'JC4827W543 4.3″ IPS', resolution: '480 × 272',
    variant: 'Choose the capacitive-touch version with GT911.',
    links: [['AliExpress', 'https://s.click.aliexpress.com/e/_oEHbBud']] },
  { target: 'ST7701_320X820', name: 'Waveshare ESP32-S3 LCD 3.16″', resolution: '320 × 820',
    variant: 'ST7701 display controller.',
    links: [['Amazon', 'https://amzn.to/4689Mbm'], ['AliExpress', 'https://s.click.aliexpress.com/e/_c4S9IVQB']] },
  { target: 'ESP32_C6_LCD_147', name: 'Waveshare ESP32-C6 LCD 1.47″', resolution: '172 × 320',
    variant: 'Choose the ESP32-C6 model.',
    links: [['Amazon', 'https://amzn.to/3ZzfcZr'], ['AliExpress', 'https://s.click.aliexpress.com/e/_okJAvee']] },
  { target: 'CHEAP_YELLOW_DISPLAY', name: 'Cheap Yellow Display 2.8″', resolution: '240 × 320',
    variant: 'ESP32-2432S028R with ILI9341 display controller.',
    links: [['Amazon', 'https://amzn.to/4kAyDJh'], ['AliExpress', 'https://s.click.aliexpress.com/e/_oCVWMbC']] },
  { target: 'ESP32_S3_AMOLED_143', name: 'Waveshare ESP32-S3 Touch AMOLED 1.43″', resolution: '466 × 466',
    variant: 'Round AMOLED display.',
    links: [['Amazon', 'https://amzn.to/41VszVi'], ['AliExpress', 'https://s.click.aliexpress.com/e/_ondyHh3']] }
]

// Start one shared sequence once the dialog and every image are ready.
const animateBoards = computed(() => open.value && dialogEntered.value
  && boards.every(board => readyImages.value.has(board.target)))
watch(open, () => { dialogEntered.value = false })

function imageReady(target) {
  readyImages.value.add(target)
}
</script>

<template>
  <div :class="compact ? 'mt-3' : 'board-shopping-intro mb-6'">
    <template v-if="!compact">
      <h2 class="text-subtitle-1 font-weight-bold">Don’t have a display?</h2>
      <p class="text-body-2 mb-3">Choose a supported board to use with ESPImageServer.</p>
    </template>
    <v-btn color="primary" variant="tonal" prepend-icon="mdi-cart-outline" @click="open = true">Buy a supported board</v-btn>
  </div>
  <v-dialog v-model="open" max-width="1320" scrollable aria-label="Buy a supported board" @after-enter="dialogEntered = open">
    <v-card>
      <v-card-title class="d-flex align-center ga-2">
        <span class="board-shopping-heading">Buy a supported board</span>
        <v-spacer />
        <v-btn icon="mdi-close" variant="text" aria-label="Close supported boards" @click="open = false" />
      </v-card-title>
      <v-card-text>
        <p class="mb-2">Check the model and variant below when ordering. Store links open in your browser.</p>
        <p class="text-caption text-medium-emphasis mb-4">Some purchase links are affiliate links.</p>
        <div class="board-shopping-grid" :class="{ 'board-shopping-grid--opening': open, 'board-shopping-grid--animate': animateBoards }">
          <v-card v-for="(board, index) in boards" :key="board.target" variant="outlined" class="board-shopping-card" :style="{ '--board-reveal-delay': `${160 + index * 280}ms` }">
            <div class="board-shopping-preview" :class="`board-shopping-preview--${board.target}`">
              <img :src="`/ui/board-catalog/${board.target}.png`" :alt="board.name" class="board-shopping-photo" @load="imageReady(board.target)" @error="imageReady(board.target)" />
            </div>
            <v-card-text class="flex-grow-1">
              <h3 class="text-subtitle-1 font-weight-bold">{{ board.name }}</h3>
              <p>{{ board.resolution }} pixels</p>
              <p class="text-body-2 mt-2">{{ board.variant }}</p>
            </v-card-text>
            <v-card-actions class="flex-wrap px-4 pb-4 ga-2">
              <v-btn v-for="[store, url] in board.links" :key="store" :href="url" target="_blank"
                rel="noopener noreferrer sponsored" color="primary" variant="tonal" append-icon="mdi-open-in-new"
                :aria-label="`Buy ${board.name} on ${store}`">Buy on {{ store }}</v-btn>
            </v-card-actions>
          </v-card>
        </div>
      </v-card-text>
    </v-card>
  </v-dialog>
</template>

<style scoped>
.board-shopping-intro { padding: 16px; border: 1px solid rgba(var(--v-border-color), var(--v-border-opacity)); border-radius: 8px; }
.board-shopping-heading { white-space: normal; }
.board-shopping-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(min(100%, 320px), 1fr)); gap: 16px; }
.board-shopping-card { display: flex; flex-direction: column; min-width: 0; border-radius: 12px; }
.board-shopping-preview {
  --board-accent: 56, 189, 248;
  position: relative;
  isolation: isolate;
  height: 180px;
  flex-shrink: 0;
  padding: 12px;
  overflow: hidden;
  border-bottom: 1px solid rgba(var(--board-accent), .2);
  background:
    radial-gradient(ellipse at 50% 80%, rgba(var(--board-accent), .24), transparent 70%),
    linear-gradient(135deg, rgba(var(--board-accent), .16), rgba(var(--board-accent), .03)),
    rgb(var(--v-theme-surface));
}
.board-shopping-preview--ST7701_320X820 { --board-accent: 45, 212, 191; }
.board-shopping-preview--ESP32_C6_LCD_147 { --board-accent: 167, 139, 250; }
.board-shopping-preview--CHEAP_YELLOW_DISPLAY { --board-accent: 251, 191, 36; }
.board-shopping-preview--ESP32_S3_AMOLED_143 { --board-accent: 244, 114, 182; }
.board-shopping-photo { position: relative; z-index: 1; display: block; width: 100%; height: 100%; object-fit: contain; filter: drop-shadow(0 8px 10px rgba(0, 0, 0, .24)); }
.board-shopping-preview::before,
.board-shopping-preview::after { content: ''; position: absolute; pointer-events: none; opacity: 0; }
.board-shopping-preview::before {
  inset: 0;
  background: radial-gradient(ellipse at 50% 70%, rgba(var(--board-accent), .42), transparent 68%);
}
.board-shopping-preview::after {
  z-index: 2;
  inset: -60% -35%;
  background: linear-gradient(115deg, transparent 43%, rgba(var(--board-accent), .12) 47%, rgba(255, 255, 255, .3) 50%, rgba(var(--board-accent), .12) 53%, transparent 57%);
}
.board-shopping-grid--opening .board-shopping-photo { opacity: 0; }
.board-shopping-grid--animate .board-shopping-photo { animation: board-photo-reveal 1150ms cubic-bezier(.22, 1, .36, 1) var(--board-reveal-delay) both; }
.board-shopping-grid--animate .board-shopping-preview::before { animation: board-preview-glow 1400ms ease-out var(--board-reveal-delay) both; }
.board-shopping-grid--animate .board-shopping-preview::after { animation: board-preview-sweep 1200ms ease-in-out var(--board-reveal-delay) both; }
@keyframes board-photo-reveal {
  0% { opacity: 0; transform: perspective(800px) translate3d(0, 28px, 0) rotateX(12deg) rotateZ(-3deg) scale(.86); }
  45% { opacity: 1; transform: perspective(800px) translate3d(0, -7px, 0) rotateX(-2deg) rotateZ(1deg) scale(1.025); }
  72% { opacity: 1; transform: perspective(800px) translate3d(0, 2px, 0) rotateX(0) rotateZ(0) scale(.995); }
  100% { opacity: 1; transform: none; }
}
@keyframes board-preview-glow {
  0% { opacity: 0; transform: scale(.75); }
  35% { opacity: 1; transform: scale(1.08); }
  100% { opacity: 0; transform: scale(1.2); }
}
@keyframes board-preview-sweep {
  0%, 12% { opacity: 0; transform: translate3d(-65%, 0, 0); }
  35% { opacity: .8; }
  75% { opacity: .55; }
  100% { opacity: 0; transform: translate3d(65%, 0, 0); }
}
@media (prefers-reduced-motion: reduce) {
  .board-shopping-grid .board-shopping-photo { animation: none; opacity: 1; transform: none; }
  .board-shopping-grid .board-shopping-preview::before,
  .board-shopping-grid .board-shopping-preview::after { animation: none; opacity: 0; }
}
</style>
