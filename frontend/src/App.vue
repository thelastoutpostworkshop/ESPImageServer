<script setup>
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { useDisplay } from 'vuetify'

function createRandomSeed() {
  return Math.floor(Math.random() * 4_294_967_296)
}

const generationSettingsKey = 'esp-image-server.generation-settings'

function loadGenerationSettings() {
  try {
    const saved = JSON.parse(window.localStorage.getItem(generationSettingsKey) || '{}')
    return {
      prompt: typeof saved.prompt === 'string' ? saved.prompt : 'A cheerful small robot holding a paintbrush, friendly illustration',
      steps: Number.isInteger(saved.steps) ? saved.steps : 1,
      seed: Number.isInteger(saved.seed) ? saved.seed : createRandomSeed(),
      modelId: typeof saved.modelId === 'string' ? saved.modelId : ''
    }
  } catch {
    return { prompt: 'A cheerful small robot holding a paintbrush, friendly illustration', steps: 1, seed: createRandomSeed(), modelId: '' }
  }
}

const savedGenerationSettings = loadGenerationSettings()
const prompt = ref(savedGenerationSettings.prompt)
const serverInfo = ref(null)
const health = ref(null)
const display = ref(null)
const displayRotation = ref(0)
const models = ref([])
const status = ref('')
const error = ref('')
const imageUrl = ref('')
const previewUrl = ref('')
const previewRotation = ref(0)
const metadataPane = ref(false)
const generatedMetadata = ref(null)
const recalledMetadata = ref(null)
const metadataError = ref('')
const generating = ref(false)
const cancelling = ref(false)
const activeJobId = ref('')
const generationProgress = ref(0)
const generationStage = ref('')
const steps = ref(savedGenerationSettings.steps)
const seed = ref(savedGenerationSettings.seed)
const activeModelId = ref(savedGenerationSettings.modelId)
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
const rotationOptions = [
  { title: 'Normal (0°)', value: 0 },
  { title: 'Rotate 90° clockwise', value: 90 },
  { title: 'Rotate 180°', value: 180 },
  { title: 'Rotate 90° counter-clockwise', value: 270 }
]
const jpegMetadataPrefix = 'ESPImageServer metadata:'

watch([prompt, steps, seed, activeModelId], () => {
  window.localStorage.setItem(generationSettingsKey, JSON.stringify({
    prompt: prompt.value,
    steps: Number(steps.value),
    seed: seed.value === '' ? null : Number(seed.value),
    modelId: activeModelId.value
  }))
})

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

async function loadDisplaySettings() {
  try {
    const settings = await fetch('/display-settings').then(response => response.json())
    displayRotation.value = settings.rotation
  } catch {
    displayRotation.value = 0
  }
}

async function setDisplayRotation(rotation) {
  const previousRotation = displayRotation.value
  displayRotation.value = rotation
  error.value = ''
  try {
    const response = await fetch('/display-settings', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ rotation })
    })
    if (!response.ok) {
      const body = await response.json().catch(() => ({}))
      throw new Error(body.detail || `Request failed (${response.status})`)
    }
    const settings = await response.json()
    displayRotation.value = settings.rotation
    status.value = 'Image rotation saved. It will be used for the next image.'
  } catch (requestError) {
    displayRotation.value = previousRotation
    error.value = `Could not save image rotation: ${requestError.message}`
  }
}

async function loadModels() {
  try {
    models.value = await fetch('/models').then(response => response.json())
    const activeModel = models.value.find(model => model.active)
    if (activeModel && activeModel.id !== activeModelId.value) {
      activeModelId.value = activeModel.id
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

function chooseRandomSeed() {
  seed.value = createRandomSeed()
}

function buildGenerationMetadata() {
  const activeModel = models.value.find(model => model.active)
  return {
    version: 1,
    createdAt: new Date().toISOString(),
    model: { id: activeModelId.value, name: activeModel?.name || activeModelId.value },
    prompt: prompt.value,
    steps: Number(steps.value),
    seed: seed.value === '' ? null : Number(seed.value),
    rotation: displayRotation.value,
    display: display.value?.connected
      ? { name: display.value.name, width: display.value.width, height: display.value.height }
      : null
  }
}

async function embedMetadataInJpeg(imageBlob, metadata) {
  const imageBytes = new Uint8Array(await imageBlob.arrayBuffer())
  if (imageBytes.length < 2 || imageBytes[0] !== 0xff || imageBytes[1] !== 0xd8) return imageBlob
  const payload = new TextEncoder().encode(`${jpegMetadataPrefix}${JSON.stringify(metadata)}`)
  if (payload.length > 65_533) return imageBlob

  const segment = new Uint8Array(payload.length + 4)
  segment[0] = 0xff
  segment[1] = 0xfe
  const length = payload.length + 2
  segment[2] = length >> 8
  segment[3] = length & 0xff
  segment.set(payload, 4)
  return new Blob([imageBytes.slice(0, 2), segment, imageBytes.slice(2)], { type: 'image/jpeg' })
}

function readMetadataFromJpeg(imageBytes) {
  if (imageBytes.length < 4 || imageBytes[0] !== 0xff || imageBytes[1] !== 0xd8) return null
  const decoder = new TextDecoder()
  let position = 2
  while (position + 4 <= imageBytes.length) {
    if (imageBytes[position] !== 0xff) break
    while (imageBytes[position] === 0xff) position += 1
    const marker = imageBytes[position]
    position += 1
    if (marker === 0xda || marker === 0xd9) break
    if (marker === 0x01 || (marker >= 0xd0 && marker <= 0xd7)) continue
    if (position + 2 > imageBytes.length) break
    const length = (imageBytes[position] << 8) | imageBytes[position + 1]
    if (length < 2 || position + length > imageBytes.length) break
    if (marker === 0xfe) {
      const comment = decoder.decode(imageBytes.slice(position + 2, position + length))
      if (comment.startsWith(jpegMetadataPrefix)) {
        try {
          return JSON.parse(comment.slice(jpegMetadataPrefix.length))
        } catch {
          return null
        }
      }
    }
    position += length
  }
  return null
}

async function loadSavedImageMetadata(files) {
  const file = Array.isArray(files) ? files[0] : files
  recalledMetadata.value = null
  metadataError.value = ''
  if (!file) return
  const metadata = readMetadataFromJpeg(new Uint8Array(await file.arrayBuffer()))
  if (!metadata?.prompt || !metadata?.model?.id) {
    metadataError.value = 'No ESPImageServer generation details were found in this JPEG.'
    return
  }
  recalledMetadata.value = metadata
}

async function useRecalledSettings() {
  const metadata = recalledMetadata.value
  if (!metadata) return
  prompt.value = metadata.prompt
  steps.value = metadata.steps
  seed.value = metadata.seed ?? createRandomSeed()
  if (rotationOptions.some(option => option.value === metadata.rotation)) {
    await setDisplayRotation(metadata.rotation)
  }
  if (metadata.model.id !== activeModelId.value) selectModelById(metadata.model.id)
  status.value = 'Saved image settings restored to the generator.'
  page.value = 'generate'
  metadataPane.value = false
}

async function createOrientedPreview(blob, rotation) {
  if (rotation === 0 || typeof window.createImageBitmap !== 'function') {
    return URL.createObjectURL(blob)
  }

  const source = await window.createImageBitmap(blob)
  const quarterTurn = rotation === 90 || rotation === 270
  const canvas = document.createElement('canvas')
  canvas.width = quarterTurn ? source.height : source.width
  canvas.height = quarterTurn ? source.width : source.height
  const context = canvas.getContext('2d')
  if (!context) {
    source.close()
    return URL.createObjectURL(blob)
  }

  // The server JPEG is already rotated for the physical display. Undo that
  // transform in the browser so the preview matches the display's orientation.
  if (rotation === 90) {
    context.translate(0, canvas.height)
    context.rotate(-Math.PI / 2)
  } else if (rotation === 180) {
    context.translate(canvas.width, canvas.height)
    context.rotate(Math.PI)
  } else {
    context.translate(canvas.width, 0)
    context.rotate(Math.PI / 2)
  }
  context.drawImage(source, 0, 0)
  source.close()
  const previewBlob = await new Promise(resolve => canvas.toBlob(resolve, 'image/jpeg', 0.92))
  return URL.createObjectURL(previewBlob || blob)
}

function useRecommendedSteps() {
  const activeModel = models.value.find(model => model.active)
  if (activeModel) steps.value = activeModel.default_steps
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
    const rawImageBlob = await imageResponse.blob()
    const metadata = buildGenerationMetadata()
    const imageBlob = await embedMetadataInJpeg(rawImageBlob, metadata)
    const rotationForImage = displayRotation.value
    if (imageUrl.value) URL.revokeObjectURL(imageUrl.value)
    if (previewUrl.value) URL.revokeObjectURL(previewUrl.value)
    imageUrl.value = URL.createObjectURL(imageBlob)
    previewUrl.value = await createOrientedPreview(imageBlob, rotationForImage)
    previewRotation.value = rotationForImage
    generatedMetadata.value = metadata
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
  await loadDisplaySettings()
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
  if (previewUrl.value) URL.revokeObjectURL(previewUrl.value)
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
      <v-btn icon="mdi-image-text" variant="text" aria-label="Saved image details" @click="metadataPane = true" />
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

    <v-navigation-drawer v-model="metadataPane" location="right" width="380" temporary border>
      <div class="d-flex align-center pa-4">
        <div>
          <div class="text-h6">Saved image details</div>
          <div class="text-caption text-medium-emphasis">Keep or restore generation settings.</div>
        </div>
        <v-spacer />
        <v-btn icon="mdi-close" variant="text" aria-label="Close saved image details" @click="metadataPane = false" />
      </div>
      <v-divider />
      <div class="pa-4">
        <div class="text-subtitle-1 font-weight-bold mb-2">Save current image</div>
        <p class="text-body-2 text-medium-emphasis mb-3">The downloaded JPEG includes its model, prompt, steps, seed, and rotation.</p>
        <v-btn v-if="imageUrl" :href="imageUrl" download="esp-image.jpg" color="primary" prepend-icon="mdi-download">Save JPEG with details</v-btn>
        <v-alert v-else type="info" variant="tonal" density="compact">Generate an image first.</v-alert>
        <div v-if="generatedMetadata" class="text-caption text-medium-emphasis mt-3">
          Ready to save: {{ generatedMetadata.model.name }}, {{ generatedMetadata.steps }} steps, seed {{ generatedMetadata.seed }}.
        </div>

        <v-divider class="my-6" />
        <div class="text-subtitle-1 font-weight-bold mb-2">Recall a saved image</div>
        <p class="text-body-2 text-medium-emphasis mb-3">Select a JPEG previously saved from ESPImageServer.</p>
        <v-file-input accept="image/jpeg,.jpg,.jpeg" label="Saved JPEG" variant="outlined" density="comfortable" prepend-icon="mdi-folder-open" @update:model-value="loadSavedImageMetadata" />
        <v-alert v-if="metadataError" type="warning" variant="tonal" density="compact" class="mb-3">{{ metadataError }}</v-alert>
        <template v-if="recalledMetadata">
          <v-list class="metadata-list" density="compact" lines="two">
            <v-list-item prepend-icon="mdi-brain" title="Model" :subtitle="recalledMetadata.model.name" />
            <v-list-item prepend-icon="mdi-text" title="Prompt" :subtitle="recalledMetadata.prompt" />
            <v-list-item prepend-icon="mdi-foot-print" title="Steps" :subtitle="String(recalledMetadata.steps)" />
            <v-list-item prepend-icon="mdi-dice-5" title="Seed" :subtitle="recalledMetadata.seed === null ? 'Random seed' : String(recalledMetadata.seed)" />
            <v-list-item prepend-icon="mdi-rotate-right" title="Rotation" :subtitle="`${recalledMetadata.rotation || 0}°`" />
          </v-list>
          <v-btn color="primary" block prepend-icon="mdi-restore" :disabled="generationBusy" @click="useRecalledSettings">Use these settings</v-btn>
        </template>
      </div>
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
              <v-select
                :model-value="displayRotation"
                :items="rotationOptions"
                label="Image rotation"
                variant="outlined"
                density="comfortable"
                :disabled="generationBusy"
                hint="Applied by ESPImageServer before the JPEG is sent. Your ESP32 firmware does not need to change."
                persistent-hint
                class="mb-4"
                @update:model-value="setDisplayRotation"
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
                <strong>Steps</strong> trade speed for detail: more steps take longer. <strong>Seed</strong> lets you repeat a result. Use Create random seed for a fresh image variation.
              </v-alert>
              <v-row dense class="mb-6">
                <v-col cols="12" sm="6">
                  <v-text-field v-model.number="steps" label="Generation steps" type="number" :min="models.find(model => model.active)?.minimum_steps" :max="models.find(model => model.active)?.maximum_steps" variant="outlined" density="comfortable" hint="More steps can improve detail. Use the reset icon for this model's recommendation." persistent-hint append-inner-icon="mdi-restore" @click:append-inner="useRecommendedSteps" />
                </v-col>
                <v-col cols="12" sm="6">
                  <v-text-field v-model="seed" label="Seed" type="number" min="0" max="4294967295" variant="outlined" density="comfortable" hint="Use the same seed to reproduce an image." persistent-hint append-inner-icon="mdi-dice-5" @click:append-inner="chooseRandomSeed" />
                  <v-btn class="mt-1" size="small" variant="text" prepend-icon="mdi-dice-5" @click="chooseRandomSeed">Create random seed</v-btn>
                </v-col>
              </v-row>
              <v-btn type="submit" color="primary" :disabled="generating" prepend-icon="mdi-image-plus">
                Generate image
              </v-btn>
              <v-btn v-if="activeJobId" class="ml-2" color="warning" variant="tonal" :loading="cancelling" :disabled="cancelling" prepend-icon="mdi-cancel" @click="cancelGeneration">
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
          <v-img v-if="previewUrl" :src="previewUrl" alt="Generated image in the selected display orientation" />
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
            <v-chip v-if="previewRotation" size="small" variant="tonal" prepend-icon="mdi-rotate-right">
              Preview: display rotation
            </v-chip>
            <v-btn :href="imageUrl" download="esp-image.jpg" color="secondary" prepend-icon="mdi-download">
              Download JPEG
            </v-btn>
            <v-btn variant="text" prepend-icon="mdi-image-text" @click="metadataPane = true">Saved image details</v-btn>
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
