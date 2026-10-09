<script setup>
import { ref } from 'vue'

defineProps({ compact: Boolean })
const open = ref(false)
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
</script>

<template>
  <div :class="compact ? 'mt-3' : 'board-shopping-intro mb-6'">
    <template v-if="!compact">
      <h2 class="text-subtitle-1 font-weight-bold">Don’t have a display?</h2>
      <p class="text-body-2 mb-3">Choose a supported board to use with ESPImageServer.</p>
    </template>
    <v-btn color="primary" variant="tonal" prepend-icon="mdi-cart-outline" @click="open = true">Buy a supported board</v-btn>
  </div>
  <v-dialog v-model="open" max-width="1320" scrollable aria-label="Buy a supported board">
    <v-card>
      <v-card-title class="d-flex align-center ga-2">
        <span class="board-shopping-heading">Buy a supported board</span>
        <v-spacer />
        <v-btn icon="mdi-close" variant="text" aria-label="Close supported boards" @click="open = false" />
      </v-card-title>
      <v-card-text>
        <p class="mb-2">Check the model and variant below when ordering. Store links open in your browser.</p>
        <p class="text-caption text-medium-emphasis mb-4">Some purchase links are affiliate links.</p>
        <div class="board-shopping-grid">
          <v-card v-for="board in boards" :key="board.target" variant="outlined" class="board-shopping-card">
            <div class="board-shopping-preview" :class="`board-shopping-preview--${board.target}`">
              <img :src="`/ui/board-catalog/${board.target}.png`" :alt="board.name" class="board-shopping-photo" />
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
.board-shopping-photo { display: block; width: 100%; height: 100%; object-fit: contain; filter: drop-shadow(0 8px 10px rgba(0, 0, 0, .24)); }
</style>
