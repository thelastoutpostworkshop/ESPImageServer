<script setup>
import { computed, onMounted, onUnmounted, ref } from 'vue'

const prompt = ref('A cheerful small robot holding a paintbrush, friendly illustration')
const serverInfo = ref(null)
const display = ref(null)
const status = ref('')
const error = ref('')
const imageUrl = ref('')
const generating = ref(false)
const heroImageUrl = '/assets/welcome-hero-horizontal.png'
const logoImageUrl = '/assets/test-page-logo.png'
let displayTimer

const displayMessage = computed(() => {
  if (!display.value?.connected) return 'Waiting for the ESP32 board to report its integrated display...'
  return `${display.value.name} connected — ${display.value.width} × ${display.value.height}. Images will fit this screen.`
})

async function loadDisplay() {
  try {
    display.value = await fetch('/display').then(response => response.json())
  } catch {
    display.value = null
  }
}

async function generate() {
  generating.value = true
  error.value = ''
  status.value = 'Generating your image. This can take a little while.'
  try {
    const response = await fetch('/generate', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ prompt: prompt.value })
    })
    if (!response.ok) {
      const body = await response.json().catch(() => ({}))
      throw new Error(body.detail || `Request failed (${response.status})`)
    }
    if (imageUrl.value) URL.revokeObjectURL(imageUrl.value)
    imageUrl.value = URL.createObjectURL(await response.blob())
    status.value = 'Image ready. Your ESP32 display will pick it up shortly.'
  } catch (requestError) {
    error.value = `Could not generate the image: ${requestError.message}`
    status.value = ''
  } finally {
    generating.value = false
  }
}

onMounted(async () => {
  try {
    serverInfo.value = await fetch('/server-info').then(response => response.json())
  } catch {
    error.value = 'Image generator information is unavailable.'
  }
  await loadDisplay()
  displayTimer = window.setInterval(loadDisplay, 5000)
})

onUnmounted(() => {
  window.clearInterval(displayTimer)
  if (imageUrl.value) URL.revokeObjectURL(imageUrl.value)
})
</script>

<template>
  <v-app>
    <v-main class="app-shell">
      <v-container class="py-7" style="max-width: 820px">
        <v-card class="hero mb-6" border elevation="4">
          <v-img :src="heroImageUrl" alt="ESPImageServer: local AI images for ESP32 displays" cover />
        </v-card>

        <v-sheet class="d-flex align-center ga-4 mb-6" color="transparent">
          <v-avatar :image="logoImageUrl" size="72" />
          <div>
            <h1 class="text-h4 font-weight-bold">Generate an image</h1>
            <template v-if="serverInfo">
              <div class="text-body-1 font-weight-bold">AI model: {{ serverInfo.model_name }}</div>
              <div class="text-body-2 text-medium-emphasis">{{ serverInfo.model_description }}</div>
              <div class="text-body-2 text-medium-emphasis">{{ serverInfo.processing }}</div>
            </template>
            <div v-else class="text-body-2 text-medium-emphasis">Checking image generator...</div>
          </div>
        </v-sheet>

        <v-card class="mb-5" variant="tonal">
          <v-card-title class="d-flex align-center ga-2">
            <v-icon icon="mdi-monitor-dashboard" color="primary" />
            ESP32 display
          </v-card-title>
          <v-card-text>{{ displayMessage }}</v-card-text>
        </v-card>

        <v-card>
          <v-card-text>
            <v-form @submit.prevent="generate">
              <v-textarea
                v-model="prompt"
                label="Describe an image"
                maxlength="1000"
                counter="1000"
                required
                variant="outlined"
                rows="4"
              />
              <v-btn type="submit" color="primary" :loading="generating" prepend-icon="mdi-image-plus">
                Generate image
              </v-btn>
              <v-alert v-if="status" class="mt-4" type="success" variant="tonal" density="compact">
                {{ status }}
              </v-alert>
              <v-alert v-if="error" class="mt-4" type="error" variant="tonal" density="compact">
                {{ error }}
              </v-alert>
            </v-form>
          </v-card-text>
        </v-card>

        <v-card v-if="imageUrl" class="mt-5">
          <v-img :src="imageUrl" alt="Generated image" />
          <v-card-actions>
            <v-btn :href="imageUrl" download="esp-image.jpg" color="secondary" prepend-icon="mdi-download">
              Download JPEG
            </v-btn>
          </v-card-actions>
        </v-card>
      </v-container>
    </v-main>
  </v-app>
</template>
