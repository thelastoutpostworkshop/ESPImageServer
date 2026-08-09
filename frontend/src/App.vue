<script setup>
import { computed, onMounted, onUnmounted, ref } from 'vue'

const prompt = ref('A cheerful small robot holding a paintbrush, friendly illustration')
const serverInfo = ref(null)
const health = ref(null)
const display = ref(null)
const models = ref([])
const status = ref('')
const error = ref('')
const imageUrl = ref('')
const generating = ref(false)
const logoImageUrl = '/assets/test-page-logo.png'
const drawer = ref(true)
const page = ref('generate')
let statusTimer

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

async function loadModels() {
  try {
    models.value = await fetch('/models').then(response => response.json())
  } catch {
    models.value = []
  }
}

async function loadServerStatus() {
  try {
    const [info, currentHealth] = await Promise.all([
      fetch('/server-info').then(response => response.json()),
      fetch('/health').then(response => response.json())
    ])
    serverInfo.value = info
    health.value = currentHealth
  } catch {
    health.value = null
  }
}

async function selectModel(model) {
  if (model.active) return
  generating.value = true
  error.value = ''
  status.value = `${model.installed ? 'Loading' : 'Downloading and loading'} ${model.name}. This can take a few minutes.`
  try {
    const response = await fetch(`/models/${encodeURIComponent(model.id)}/select`, { method: 'POST' })
    if (!response.ok) {
      const body = await response.json().catch(() => ({}))
      throw new Error(body.detail || `Request failed (${response.status})`)
    }
    await Promise.all([loadServerStatus(), loadModels()])
    status.value = `${model.name} is ready to generate images.`
    page.value = 'generate'
  } catch (requestError) {
    error.value = `Could not change the image model: ${requestError.message}`
    status.value = ''
  } finally {
    generating.value = false
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
  await loadServerStatus()
  await loadDisplay()
  await loadModels()
  statusTimer = window.setInterval(() => {
    loadServerStatus()
    loadDisplay()
    loadModels()
  }, 5000)
})

onUnmounted(() => {
  window.clearInterval(statusTimer)
  if (imageUrl.value) URL.revokeObjectURL(imageUrl.value)
})
</script>

<template>
  <v-app>
    <v-app-bar color="surface" border elevation="2">
      <v-app-bar-nav-icon aria-label="Toggle navigation" @click="drawer = !drawer" />
      <v-avatar :image="logoImageUrl" size="36" class="mr-3" />
      <v-app-bar-title class="font-weight-bold">ESPImageServer</v-app-bar-title>
      <v-chip class="mr-2" :color="health?.status === 'ready' ? 'success' : 'warning'" variant="tonal" prepend-icon="mdi-server">
        {{ health?.status === 'ready' ? 'Server ready' : 'Server loading' }}
      </v-chip>
      <v-chip v-if="serverInfo" class="mr-2" color="primary" variant="tonal" prepend-icon="mdi-brain">
        {{ serverInfo.model_name }}
      </v-chip>
      <v-chip :color="display?.connected ? 'info' : 'warning'" variant="tonal" prepend-icon="mdi-monitor-dashboard">
        {{ display?.connected ? `${display.name} · ${display.width}×${display.height}` : 'Display waiting' }}
      </v-chip>
    </v-app-bar>

    <v-navigation-drawer v-model="drawer" width="272" border>
      <v-list-item class="py-4" title="ESPImageServer" subtitle="Local AI image generation" />
      <v-divider />
      <v-list nav density="comfortable">
        <v-list-item prepend-icon="mdi-image-sparkles" title="Generate image" :active="page === 'generate'" @click="page = 'generate'" />
        <v-list-item prepend-icon="mdi-brain" title="Models" :active="page === 'models'" @click="page = 'models'" />
        <v-list-item prepend-icon="mdi-information-outline" title="About" :active="page === 'about'" @click="page = 'about'" />
      </v-list>
      <template #append>
        <div class="pa-4 text-caption text-medium-emphasis">Images stay on your local network.</div>
      </template>
    </v-navigation-drawer>

    <v-main class="app-shell">
      <v-container class="py-7" style="max-width: 820px">
        <template v-if="page === 'generate'">
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
        </template>

        <v-card v-else-if="page === 'models'">
          <v-card-title class="text-h4 pt-6">Choose an image model</v-card-title>
          <v-card-text class="text-body-1">
            Choose how ESPImageServer creates images. Each model downloads once and stays on this computer.
          </v-card-text>
          <v-card-text class="pt-0">
            <v-row>
              <v-col v-for="model in models" :key="model.id" cols="12" md="6">
                <v-card class="model-card h-100" :class="{ 'model-card--active': model.active }" border elevation="3">
                  <v-card-item>
                    <template #prepend>
                      <v-avatar :color="model.hardware.includes('NVIDIA') ? 'deep-purple' : 'teal'" variant="tonal" size="48">
                        <v-icon>{{ model.hardware.includes('NVIDIA') ? 'mdi-expansion-card-variant' : 'mdi-laptop' }}</v-icon>
                      </v-avatar>
                    </template>
                    <v-card-title>{{ model.name }}</v-card-title>
                    <v-card-subtitle>{{ model.speed }}</v-card-subtitle>
                  </v-card-item>
                  <v-card-text>
                    <p class="mb-4">{{ model.description }}</p>
                    <v-alert :color="model.hardware.includes('NVIDIA') ? 'deep-purple' : 'teal'" variant="tonal" density="comfortable" class="mb-3">
                      <div class="font-weight-bold">{{ model.hardware }}</div>
                      <div class="text-body-2">{{ model.recommendation }}</div>
                    </v-alert>
                    <v-chip :color="model.installed ? 'success' : 'secondary'" variant="tonal" size="small" :prepend-icon="model.installed ? 'mdi-check-circle' : 'mdi-download'">
                      {{ model.installed ? 'Downloaded' : 'Download required' }}
                    </v-chip>
                  </v-card-text>
                  <v-card-actions class="px-4 pb-4">
                    <v-chip v-if="model.active" color="success" variant="flat" prepend-icon="mdi-check">Currently in use</v-chip>
                    <v-btn v-else color="primary" block :loading="generating" @click="selectModel(model)">
                      {{ model.installed ? 'Use this model' : 'Download and use' }}
                    </v-btn>
                  </v-card-actions>
                </v-card>
              </v-col>
            </v-row>
          </v-card-text>
        </v-card>

        <v-card v-else>
          <v-card-title>About ESPImageServer</v-card-title>
          <v-card-text class="text-body-1">
            Generate local AI images and show them on a connected ESP32 display. Images remain on your local network.
          </v-card-text>
          <v-list density="compact">
            <v-list-item prepend-icon="mdi-brain" title="Model" :subtitle="serverInfo?.model_description || 'Loading model information...'" />
            <v-list-item prepend-icon="mdi-monitor-dashboard" title="Display" :subtitle="displayMessage" />
          </v-list>
        </v-card>
      </v-container>
    </v-main>
  </v-app>
</template>
