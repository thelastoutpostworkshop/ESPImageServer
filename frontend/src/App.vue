<script setup>
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { useDisplay } from 'vuetify'

function createRandomSeed() {
  return Math.floor(Math.random() * 4_294_967_296)
}

const prompt = ref('A cheerful small robot holding a paintbrush, friendly illustration')
const serverInfo = ref(null)
const health = ref(null)
const display = ref(null)
const models = ref([])
const status = ref('')
const error = ref('')
const imageUrl = ref('')
const generating = ref(false)
const cancelling = ref(false)
const activeJobId = ref('')
const generationProgress = ref(0)
const generationStage = ref('')
const steps = ref(1)
const seed = ref(createRandomSeed())
const activeModelId = ref('')
const logoImageUrl = '/assets/test-page-logo.png'
const drawer = ref(true)
const page = ref('generate')
let statusTimer
const { mobile } = useDisplay()
const generationBusy = computed(() => generating.value || health.value?.generating === true)
const modelOptions = computed(() => models.value.map(model => ({
  title: `${model.name} — ${model.speed} (${model.hardware})`,
  value: model.id
})))

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
    const activeModel = models.value.find(model => model.active)
    if (activeModel && activeModel.id !== activeModelId.value) {
      activeModelId.value = activeModel.id
      steps.value = activeModel.default_steps
    }
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
  if (model.active || generationBusy.value) return
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

function selectModelById(modelId) {
  const model = models.value.find(candidate => candidate.id === modelId)
  if (model) selectModel(model)
}

async function generate() {
  generating.value = true
  error.value = ''
  status.value = ''
  generationProgress.value = 0
  generationStage.value = 'Starting image generation...'
  try {
    const response = await fetch('/generation-jobs', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        prompt: prompt.value,
        steps: Number(steps.value),
        seed: seed.value === '' ? null : Number(seed.value)
      })
    })
    if (!response.ok) {
      const body = await response.json().catch(() => ({}))
      throw new Error(body.detail || `Request failed (${response.status})`)
    }
    const job = await response.json()
    activeJobId.value = job.id
    let currentJob = job
    while (!['complete', 'failed', 'cancelled'].includes(currentJob.status)) {
      await new Promise(resolve => window.setTimeout(resolve, 350))
      const statusResponse = await fetch(`/generation-jobs/${job.id}`)
      if (!statusResponse.ok) throw new Error(`Request failed (${statusResponse.status})`)
      currentJob = await statusResponse.json()
      generationProgress.value = currentJob.progress
      generationStage.value = currentJob.steps ? `${currentJob.stage} (${currentJob.step} of ${currentJob.steps})` : currentJob.stage
    }
    if (currentJob.status === 'cancelled') {
      status.value = 'Image generation cancelled.'
      return
    }
    if (currentJob.status === 'failed') throw new Error(currentJob.error || 'Image generation failed')
    const imageResponse = await fetch(`/generation-jobs/${job.id}/image`)
    if (!imageResponse.ok) throw new Error(`Request failed (${imageResponse.status})`)
    if (imageUrl.value) URL.revokeObjectURL(imageUrl.value)
    imageUrl.value = URL.createObjectURL(await imageResponse.blob())
    status.value = 'Image ready. Your ESP32 display will pick it up shortly.'
  } catch (requestError) {
    error.value = `Could not generate the image: ${requestError.message}`
    status.value = ''
  } finally {
    generating.value = false
    cancelling.value = false
    activeJobId.value = ''
    generationProgress.value = 0
    generationStage.value = ''
  }
}

async function cancelGeneration() {
  if (!activeJobId.value || cancelling.value) return
  cancelling.value = true
  error.value = ''
  generationStage.value = 'Cancelling image generation...'
  try {
    const response = await fetch(`/generation-jobs/${activeJobId.value}`, { method: 'DELETE' })
    if (!response.ok) {
      const body = await response.json().catch(() => ({}))
      throw new Error(body.detail || `Request failed (${response.status})`)
    }
  } catch (requestError) {
    cancelling.value = false
    error.value = `Could not cancel image generation: ${requestError.message}`
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
    <v-app-bar color="surface" border elevation="2" class="app-bar">
      <v-app-bar-nav-icon aria-label="Toggle navigation" @click="drawer = !drawer" />
      <v-avatar :image="logoImageUrl" size="36" class="mr-3" />
      <v-app-bar-title class="font-weight-bold" :class="{ 'app-bar__title--compact': mobile }">ESPImageServer</v-app-bar-title>
      <v-chip class="mr-2" :color="health?.status === 'ready' ? 'success' : 'warning'" variant="tonal" prepend-icon="mdi-server">
        <span v-if="!mobile">{{ health?.status === 'ready' ? 'Server ready' : 'Server loading' }}</span>
      </v-chip>
      <v-chip v-if="!mobile" :color="display?.connected ? 'info' : 'warning'" variant="tonal" prepend-icon="mdi-monitor-dashboard">
        {{ display?.connected ? `${display.name} · ${display.width}×${display.height}` : 'Display waiting' }}
      </v-chip>
    </v-app-bar>

    <v-navigation-drawer v-model="drawer" width="272" border :temporary="mobile">
      <v-list-item class="py-4" title="ESPImageServer" subtitle="Local AI image generation" />
      <v-divider />
      <v-list nav density="comfortable">
        <v-list-item title="Generate image" :active="page === 'generate'" @click="page = 'generate'">
          <template #prepend>
            <v-avatar :image="logoImageUrl" size="26" />
          </template>
        </v-list-item>
        <v-list-item prepend-icon="mdi-brain" title="Models" :active="page === 'models'" @click="page = 'models'" />
        <v-list-item prepend-icon="mdi-information-outline" title="About" :active="page === 'about'" @click="page = 'about'" />
      </v-list>
      <template #append>
        <div class="pa-4 text-caption text-medium-emphasis">Images stay on your local network.</div>
      </template>
    </v-navigation-drawer>

    <v-main class="app-shell">
      <v-container class="app-container py-4 py-sm-7">
        <template v-if="page === 'generate'">
        <v-row>
        <v-col cols="12" lg="5">
        <v-card class="generation-card">
          <v-card-text>
            <v-form @submit.prevent="generate">
              <v-select
                :model-value="activeModelId"
                :items="modelOptions"
                label="Image model"
                variant="outlined"
                density="comfortable"
                :disabled="generationBusy || models.length === 0"
                hint="Choose a model for this computer. Models not yet downloaded will download before they are used."
                persistent-hint
                class="mb-4"
                @update:model-value="selectModelById"
              />
              <v-textarea
                v-model="prompt"
                label="Describe an image"
                maxlength="1000"
                counter="1000"
                required
                variant="outlined"
                rows="4"
              />
              <v-alert type="info" variant="tonal" density="compact" class="mb-4">
                <strong>Steps</strong> trade speed for detail: more steps take longer. <strong>Seed</strong> lets you repeat a result. Use the dice button for a new random seed.
              </v-alert>
              <v-row dense class="mb-6">
                <v-col cols="12" sm="6">
                  <v-text-field v-model.number="steps" label="Generation steps" type="number" :min="models.find(model => model.active)?.minimum_steps" :max="models.find(model => model.active)?.maximum_steps" variant="outlined" density="comfortable" hint="More steps can improve detail, but take longer." persistent-hint />
                </v-col>
                <v-col cols="12" sm="6">
                  <v-text-field v-model="seed" label="Seed" type="number" min="0" max="4294967295" variant="outlined" density="comfortable" hint="Use the same seed to reproduce an image." persistent-hint append-inner-icon="mdi-dice-5" @click:append-inner="seed = createRandomSeed()" />
                </v-col>
              </v-row>
              <v-btn type="submit" color="primary" :disabled="generating" prepend-icon="mdi-image-plus">
                Generate image
              </v-btn>
              <v-btn v-if="generating" class="ml-2" color="warning" variant="tonal" :loading="cancelling" :disabled="cancelling" prepend-icon="mdi-cancel" @click="cancelGeneration">
                Cancel generation
              </v-btn>
              <div v-if="generating" class="mt-5">
                <div class="d-flex justify-space-between text-body-2 mb-2">
                  <span>{{ generationStage }}</span><span>{{ generationProgress }}%</span>
                </div>
                <v-progress-linear :model-value="generationProgress" color="primary" height="10" rounded />
              </div>
              <v-alert v-if="status" class="mt-4" type="success" variant="tonal" density="compact">
                {{ status }}
              </v-alert>
              <v-alert v-if="error" class="mt-4" type="error" variant="tonal" density="compact">
                {{ error }}
              </v-alert>
            </v-form>
          </v-card-text>
        </v-card>
        </v-col>

        <v-col cols="12" lg="7">
        <v-card class="generated-image-card h-100">
          <v-img v-if="imageUrl" :src="imageUrl" alt="Generated image" />
          <v-sheet v-else class="preview-placeholder d-flex flex-column align-center justify-center text-center pa-8">
            <v-avatar color="primary" variant="tonal" size="64" class="mb-4">
              <v-icon size="34">mdi-image-outline</v-icon>
            </v-avatar>
            <div class="text-h6">Your generated image will appear here</div>
            <div class="text-body-2 text-medium-emphasis mt-2">
              Describe an image, choose your settings, then select Generate image.
            </div>
          </v-sheet>
          <v-card-actions v-if="imageUrl">
            <v-btn :href="imageUrl" download="esp-image.jpg" color="secondary" prepend-icon="mdi-download">
              Download JPEG
            </v-btn>
          </v-card-actions>
        </v-card>
        </v-col>
        </v-row>
        </template>

        <v-card v-else-if="page === 'models'">
          <v-card-title class="text-h5 pt-5">Image models</v-card-title>
          <v-card-text class="text-body-1">
            Compare the available models. Choose the model to use from the Generate image page; it downloads once and stays on this computer.
          </v-card-text>
          <v-table v-if="!mobile" class="model-table" hover density="comfortable">
            <thead>
              <tr>
                <th>Model</th>
                <th>Best for</th>
                <th>Hardware</th>
                <th>Status</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="model in models" :key="model.id" :class="{ 'model-table__active': model.active }">
                <td>
                  <div class="d-flex align-center ga-3 py-2">
                    <v-avatar :color="model.hardware.includes('NVIDIA') ? 'deep-purple' : 'teal'" variant="tonal" size="36">
                      <v-icon size="20">{{ model.hardware.includes('NVIDIA') ? 'mdi-expansion-card-variant' : 'mdi-laptop' }}</v-icon>
                    </v-avatar>
                    <div>
                      <div class="font-weight-bold">{{ model.name }}</div>
                      <div class="text-caption text-medium-emphasis">{{ model.speed }}</div>
                    </div>
                  </div>
                </td>
                <td class="model-table__description">{{ model.description }}</td>
                <td>
                  <v-chip :color="model.hardware.includes('NVIDIA') ? 'deep-purple' : 'teal'" variant="tonal" size="small">
                    {{ model.hardware }}
                  </v-chip>
                </td>
                <td>
                  <v-chip v-if="model.active" color="success" variant="tonal" size="small" prepend-icon="mdi-check-circle">In use</v-chip>
                  <v-chip v-else :color="model.installed ? 'success' : 'secondary'" variant="tonal" size="small" :prepend-icon="model.installed ? 'mdi-check-circle' : 'mdi-download'">
                    {{ model.installed ? 'Downloaded' : 'Download needed' }}
                  </v-chip>
                </td>
              </tr>
            </tbody>
          </v-table>
          <v-list v-else class="model-list" lines="two">
            <v-list-item v-for="model in models" :key="model.id" :class="{ 'model-list__active': model.active }">
              <template #prepend>
                <v-avatar :color="model.hardware.includes('NVIDIA') ? 'deep-purple' : 'teal'" variant="tonal" size="36">
                  <v-icon size="20">{{ model.hardware.includes('NVIDIA') ? 'mdi-expansion-card-variant' : 'mdi-laptop' }}</v-icon>
                </v-avatar>
              </template>
              <v-list-item-title class="font-weight-bold">{{ model.name }}</v-list-item-title>
              <v-list-item-subtitle>{{ model.speed }} · {{ model.hardware }}</v-list-item-subtitle>
              <template #append><v-chip v-if="model.active" color="success" variant="tonal" size="small">In use</v-chip></template>
            </v-list-item>
          </v-list>
          <v-card-text class="text-caption text-medium-emphasis pt-3">
            NVIDIA models can still run without a compatible GPU, but generation may be impractically slow.
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
