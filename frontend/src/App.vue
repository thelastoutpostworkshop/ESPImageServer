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
  <main>
    <section class="hero" aria-label="ESPImageServer welcome">
      <img :src="heroImageUrl" alt="ESPImageServer: local AI images for ESP32 displays" />
    </section>

    <section class="heading">
      <img :src="logoImageUrl" alt="ESPImageServer logo" />
      <div>
        <h1>Generate an image</h1>
        <template v-if="serverInfo">
          <p><strong>AI model: {{ serverInfo.model_name }}</strong></p>
          <p>{{ serverInfo.model_description }}</p>
          <p>{{ serverInfo.processing }}</p>
        </template>
        <p v-else>Checking image generator...</p>
      </div>
    </section>

    <section class="card display-card">
      <h2>ESP32 display</h2>
      <p>{{ displayMessage }}</p>
    </section>

    <form class="card" @submit.prevent="generate">
      <label for="prompt">Describe an image</label>
      <textarea id="prompt" v-model="prompt" maxlength="1000" required />
      <button :disabled="generating">{{ generating ? 'Generating...' : 'Generate image' }}</button>
      <p v-if="status" class="success">{{ status }}</p>
      <p v-if="error" class="error">{{ error }}</p>
    </form>

    <section v-if="imageUrl" class="card result">
      <img :src="imageUrl" alt="Generated image" />
      <a :href="imageUrl" download="esp-image.jpg">Download JPEG</a>
    </section>
  </main>
</template>
