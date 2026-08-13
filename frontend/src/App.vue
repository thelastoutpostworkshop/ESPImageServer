<script setup>
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { useDisplay } from 'vuetify'

function createRandomSeed() {
  return Math.floor(Math.random() * 4_294_967_296)
}

const generationSettingsKey = 'esp-image-server.generation-settings'
const videoGenerationSettingsKey = 'esp-image-server.video-generation-settings'
const imageLibraryPaneSettingsKey = 'esp-image-server.image-library-pane-pinned'
const imageLibraryViewSettingsKey = 'esp-image-server.image-library-view'
const imageLibraryWidthSettingsKey = 'esp-image-server.image-library-width'
const imageLibraryThumbnailSizeSettingsKey = 'esp-image-server.image-library-thumbnail-size'
const videoFrameValues = [17, 25, 33, 41, 49, 57, 65, 73, 81]

function loadImageLibraryWidth() {
  const savedWidth = Number(window.localStorage.getItem(imageLibraryWidthSettingsKey))
  return Number.isFinite(savedWidth) && savedWidth >= 300 && savedWidth <= 720 ? savedWidth : 380
}

function loadImageLibraryThumbnailSize() {
  const savedSize = Number(window.localStorage.getItem(imageLibraryThumbnailSizeSettingsKey))
  return Number.isFinite(savedSize) && savedSize >= 100 && savedSize <= 220 ? savedSize : 160
}

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

function loadVideoGenerationSettings() {
  try {
    const saved = JSON.parse(window.localStorage.getItem(videoGenerationSettingsKey) || '{}')
    return {
      prompt: typeof saved.prompt === 'string' ? saved.prompt : 'Gentle cinematic camera movement, subtle natural motion',
      frames: videoFrameValues.includes(saved.frames) ? saved.frames : 25,
      fps: [8, 12, 15, 24].includes(saved.fps) ? saved.fps : 8,
      steps: [4, 5, 6, 7, 8].includes(saved.steps) ? saved.steps : 8,
      seed: Number.isInteger(saved.seed) ? saved.seed : createRandomSeed()
    }
  } catch {
    return { prompt: 'Gentle cinematic camera movement, subtle natural motion', frames: 25, fps: 8, steps: 8, seed: createRandomSeed() }
  }
}

const savedGenerationSettings = loadGenerationSettings()
const savedVideoGenerationSettings = loadVideoGenerationSettings()
const prompt = ref(savedGenerationSettings.prompt)
const serverInfo = ref(null)
const health = ref(null)
const display = ref(null)
const displayConnectedSnackbar = ref(false)
const displayConnectedMessage = ref('')
const displayRotation = ref(0)
const models = ref([])
const status = ref('')
const error = ref('')
const imageUrl = ref('')
const videoUrl = ref('')
const videoSourceImage = ref(null)
const videoPrompt = ref(savedVideoGenerationSettings.prompt)
const videoSeed = ref(savedVideoGenerationSettings.seed)
const videoFrames = ref(savedVideoGenerationSettings.frames)
const videoFps = ref(savedVideoGenerationSettings.fps)
const videoSteps = ref(savedVideoGenerationSettings.steps)
const generatingVideo = ref(false)
const cancellingVideo = ref(false)
const activeVideoJobId = ref('')
const videoProgress = ref(0)
const videoStage = ref('')
const videoError = ref('')
const previewUrl = ref('')
const previewFittedFor = ref(null)
const metadataPane = ref(false)
const metadataPanePinned = ref(window.localStorage.getItem(imageLibraryPaneSettingsKey) === 'true')
const imageLibraryView = ref(window.localStorage.getItem(imageLibraryViewSettingsKey) === 'list' ? 'list' : 'thumbnails')
const imageLibraryWidth = ref(loadImageLibraryWidth())
const imageLibraryThumbnailSize = ref(loadImageLibraryThumbnailSize())
const generatedMetadata = ref(null)
const currentImageSavedToLibrary = ref(false)
const savingToCreationLibrary = ref(false)
const recalledMetadata = ref(null)
const savedImageContextMenu = ref(false)
const savedImageContextMenuPosition = ref([0, 0])
const contextMenuSavedImage = ref(null)
const selectedSavedImage = ref(null)
const deleteSavedImageDialog = ref(false)
const deletingSavedImage = ref(false)
const savingToDisplaySdCard = ref(false)
const displaySdCard = ref({ available: false, files: [] })
const displaySdCardLoading = ref(false)
const displayingSdCardFile = ref('')
const sdCardSnackbar = ref(false)
const sdCardSnackbarMessage = ref('')
const metadataError = ref('')
const savedImages = ref([])
const savedImagesLoading = ref(false)
const imageLibraryLocation = ref('')
const jpegQuality = ref(85)
const autoSaveImages = ref(true)
const autoSaveSaving = ref(false)
const settingsSaving = ref(false)
const openingImageLibrary = ref(false)
const choosingImageLibrary = ref(false)
const settingsStatus = ref('')
const settingsError = ref('')
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
let modelSwitchAbortController
let imageLibraryResizeStartX = 0
let imageLibraryResizeStartWidth = 0
const { mobile } = useDisplay()
const generationBusy = computed(() => generating.value || health.value?.generating === true)
const modelOptions = computed(() => models.value.map(model => ({
  title: `${model.name} — ${model.speed} (${model.hardware})`,
  value: model.id
})))
const videoFrameOptions = computed(() => videoFrameValues.map(frames => ({
  title: `${frames} frames · ${(frames / Number(videoFps.value)).toFixed(1)} seconds`,
  value: frames
})))
const rotationOptions = [
  { title: 'Normal (0°)', value: 0 },
  { title: 'Rotate 90° clockwise', value: 90 },
  { title: 'Rotate 180°', value: 180 },
  { title: 'Rotate 90° counter-clockwise', value: 270 }
]
const sdCardTableHeaders = [
  { title: 'Preview', key: 'thumbnail', sortable: false, width: '96px' },
  { title: 'File name', key: 'name' },
  { title: 'Created', key: 'created_at', width: '180px' },
  { title: 'Size', key: 'size', width: '120px', align: 'end' },
  { title: 'Actions', key: 'actions', sortable: false, align: 'end', width: '120px' }
]
const savedImageGroups = computed(() => {
  const groups = new Map()
  for (const savedImage of savedImages.value) {
    const modelName = savedImage.metadata?.model?.name || 'Other images'
    if (!groups.has(modelName)) groups.set(modelName, [])
    groups.get(modelName).push(savedImage)
  }
  return [...groups].map(([modelName, images]) => ({ modelName, images }))
})

watch([prompt, steps, seed, activeModelId], () => {
  window.localStorage.setItem(generationSettingsKey, JSON.stringify({
    prompt: prompt.value,
    steps: Number(steps.value),
    seed: seed.value === '' ? null : Number(seed.value),
    modelId: activeModelId.value
  }))
})

watch([videoPrompt, videoFrames, videoFps, videoSteps, videoSeed], () => {
  window.localStorage.setItem(videoGenerationSettingsKey, JSON.stringify({
    prompt: videoPrompt.value,
    frames: Number(videoFrames.value),
    fps: Number(videoFps.value),
    steps: Number(videoSteps.value),
    seed: videoSeed.value === '' ? null : Number(videoSeed.value)
  }))
})

watch(metadataPanePinned, pinned => {
  window.localStorage.setItem(imageLibraryPaneSettingsKey, String(pinned))
})

watch(imageLibraryView, view => {
  window.localStorage.setItem(imageLibraryViewSettingsKey, view)
})

watch(imageLibraryWidth, width => {
  window.localStorage.setItem(imageLibraryWidthSettingsKey, String(width))
})

watch(imageLibraryThumbnailSize, size => {
  window.localStorage.setItem(imageLibraryThumbnailSizeSettingsKey, String(size))
})

const displayMessage = computed(() => {
  if (!display.value?.connected) return 'Waiting for the ESP32 board to report its integrated display...'
  return `${display.value.name} connected — ${display.value.width} × ${display.value.height}. Images will fit this screen.`
})

async function loadDisplay() {
  try {
    const nextDisplay = await fetch('/display', { cache: 'no-store' }).then(response => response.json())
    const previousKey = display.value?.connected ? `${display.value.name}:${display.value.width}x${display.value.height}` : ''
    const nextKey = nextDisplay?.connected ? `${nextDisplay.name}:${nextDisplay.width}x${nextDisplay.height}` : ''
    display.value = nextDisplay
    if (nextKey && nextKey !== previousKey) {
      displayConnectedMessage.value = `${nextDisplay.name} connected (${nextDisplay.width} × ${nextDisplay.height}).`
      displayConnectedSnackbar.value = true
    }
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
    if (activeModel && !models.value.some(model => model.id === activeModelId.value)) {
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

async function prepareSelectedModel() {
  const model = models.value.find(candidate => candidate.id === activeModelId.value)
  if (!model) throw new Error('Choose an image model before generating.')
  if (model.active && health.value?.status === 'ready') return
  const abortController = new AbortController()
  modelSwitchAbortController = abortController
  generationStage.value = model.installed
    ? `Loading ${model.name}...`
    : `Downloading ${model.name}. This first download can take several minutes...`
  try {
    const response = await fetch(`/models/${encodeURIComponent(model.id)}/select`, {
      method: 'POST',
      signal: abortController.signal
    })
    if (!response.ok) {
      const body = await response.json().catch(() => ({}))
      throw new Error(body.detail || `Request failed (${response.status})`)
    }
    await Promise.all([loadServerStatus(), loadModels()])
  } catch (requestError) {
    if (requestError.name === 'AbortError') throw new Error('Image generation cancelled.')
    throw new Error(`Could not prepare ${model.name}: ${requestError.message}`)
  } finally {
    if (modelSwitchAbortController === abortController) {
      modelSwitchAbortController = undefined
    }
  }
}

function selectModelById(modelId) {
  const model = models.value.find(candidate => candidate.id === modelId)
  if (!model || generationBusy.value) return
  activeModelId.value = model.id
  steps.value = model.default_steps
}

function chooseRandomSeed() {
  seed.value = createRandomSeed()
}

function formatFileSize(bytes) {
  if (!bytes) return '0 KB'
  return bytes < 1024 * 1024
    ? `${Math.round(bytes / 1024)} KB`
    : `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}

function formatDateTime(value) {
  if (!value) return 'Unknown'
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? 'Unknown' : date.toLocaleString()
}

function showSDCardSnackbar(message) {
  sdCardSnackbarMessage.value = message
  sdCardSnackbar.value = true
}

async function loadSavedImages() {
  savedImagesLoading.value = true
  try {
    const response = await fetch('/saved-images')
    if (!response.ok) throw new Error(`Request failed (${response.status})`)
    savedImages.value = await response.json()
  } catch {
    savedImages.value = []
  } finally {
    savedImagesLoading.value = false
  }
}

async function loadDisplaySdCard() {
  displaySdCardLoading.value = true
  try {
    const response = await fetch('/display-sd-card')
    if (!response.ok) throw new Error(`Request failed (${response.status})`)
    displaySdCard.value = await response.json()
  } catch {
    displaySdCard.value = { available: false, files: [] }
  } finally {
    displaySdCardLoading.value = false
  }
}

function openGeneratePage() {
  page.value = 'generate'
  if (display.value?.connected) {
    sendDisplaySdCardCommand('/display-sd-card/mode/live_images')
  }
}

function openSDCardPage() {
  page.value = 'sd-card'
  loadDisplaySdCard()
  if (display.value?.connected) {
    sendDisplaySdCardCommand('/display-sd-card/mode/sd_card')
  }
}

async function sendDisplaySdCardCommand(endpoint, method = 'POST') {
  error.value = ''
  try {
    const response = await fetch(endpoint, { method })
    if (!response.ok) {
      const body = await response.json().catch(() => ({}))
      throw new Error(body.detail || `Request failed (${response.status})`)
    }
    showSDCardSnackbar('Request sent to the display.')
    window.setTimeout(loadDisplaySdCard, 3500)
  } catch (requestError) {
    error.value = `Could not update the display SD card: ${requestError.message}`
  }
}

async function showSDCardFileOnDisplay(filename) {
  if (displayingSdCardFile.value) return
  displayingSdCardFile.value = filename
  error.value = ''
  status.value = ''
  try {
    const response = await fetch(`/display-sd-card/files/${encodeURIComponent(filename)}/display`, { method: 'POST' })
    if (!response.ok) {
      const body = await response.json().catch(() => ({}))
      throw new Error(body.detail || `Request failed (${response.status})`)
    }
    const command = await response.json()
    for (let attempt = 0; attempt < 30; attempt += 1) {
      await new Promise(resolve => window.setTimeout(resolve, 500))
      const commandResponse = await fetch(`/display-commands/${encodeURIComponent(command.id)}`)
      if (!commandResponse.ok) throw new Error(`Could not check display status (${commandResponse.status})`)
      const result = await commandResponse.json()
      if (result.status === 'complete') {
        showSDCardSnackbar('Image is now showing on the display.')
        return
      }
      if (result.status === 'failed') throw new Error(result.detail || 'The display could not show this image')
    }
    showSDCardSnackbar('The display is still processing the image.')
  } catch (requestError) {
    error.value = `Could not show image on the display: ${requestError.message}`
  } finally {
    displayingSdCardFile.value = ''
  }
}

async function loadAppSettings() {
  try {
    const response = await fetch('/app-settings')
    if (!response.ok) throw new Error(`Request failed (${response.status})`)
    const settings = await response.json()
    imageLibraryLocation.value = settings.image_library_location
    jpegQuality.value = settings.jpeg_quality
    autoSaveImages.value = settings.auto_save_images !== false
  } catch {
    // The rest of the app remains usable while settings are unavailable.
  }
}

async function saveAppSettings() {
  settingsSaving.value = true
  settingsError.value = ''
  settingsStatus.value = ''
  try {
    const response = await fetch('/app-settings', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        image_library_location: imageLibraryLocation.value,
        jpeg_quality: Number(jpegQuality.value),
        auto_save_images: autoSaveImages.value
      })
    })
    if (!response.ok) {
      const body = await response.json().catch(() => ({}))
      throw new Error(body.detail || `Request failed (${response.status})`)
    }
    const settings = await response.json()
    imageLibraryLocation.value = settings.image_library_location
    jpegQuality.value = settings.jpeg_quality
    autoSaveImages.value = settings.auto_save_images !== false
    await loadSavedImages()
    settingsStatus.value = 'Settings saved. JPEG quality is used for new images.'
  } catch (requestError) {
    settingsError.value = `Could not save settings: ${requestError.message}`
  } finally {
    settingsSaving.value = false
  }
}

async function setAutoSaveImages(value) {
  const previousValue = autoSaveImages.value
  autoSaveImages.value = value
  autoSaveSaving.value = true
  error.value = ''
  try {
    const response = await fetch('/app-settings', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ auto_save_images: value })
    })
    if (!response.ok) {
      const body = await response.json().catch(() => ({}))
      throw new Error(body.detail || `Request failed (${response.status})`)
    }
    const settings = await response.json()
    autoSaveImages.value = settings.auto_save_images !== false
  } catch (requestError) {
    autoSaveImages.value = previousValue
    error.value = `Could not update automatic saving: ${requestError.message}`
  } finally {
    autoSaveSaving.value = false
  }
}

async function revealImageLibrary() {
  openingImageLibrary.value = true
  settingsError.value = ''
  try {
    if (window.espImageServerDesktop?.revealImageLibrary) {
      const failure = await window.espImageServerDesktop.revealImageLibrary(imageLibraryLocation.value)
      if (failure) throw new Error(failure)
    } else {
      const response = await fetch('/app-settings/image-library/reveal', { method: 'POST' })
      if (!response.ok) {
        const body = await response.json().catch(() => ({}))
        throw new Error(body.detail || `Request failed (${response.status})`)
      }
    }
  } catch (requestError) {
    settingsError.value = `Could not open the image library folder: ${requestError.message}`
  } finally {
    openingImageLibrary.value = false
  }
}

async function chooseImageLibrary() {
  choosingImageLibrary.value = true
  settingsError.value = ''
  try {
    if (window.espImageServerDesktop?.chooseImageLibrary) {
      const selectedPath = await window.espImageServerDesktop.chooseImageLibrary()
      if (selectedPath) imageLibraryLocation.value = selectedPath
    } else {
      const response = await fetch('/app-settings/image-library/choose', { method: 'POST' })
      if (!response.ok) {
        const body = await response.json().catch(() => ({}))
        throw new Error(body.detail || `Request failed (${response.status})`)
      }
      const selection = await response.json()
      if (selection.selected) imageLibraryLocation.value = selection.image_library_location
    }
  } catch (requestError) {
    settingsError.value = `Could not open the folder chooser: ${requestError.message}`
  } finally {
    choosingImageLibrary.value = false
  }
}

async function openMetadataPane() {
  metadataPane.value = true
  await loadSavedImages()
  await loadDisplaySdCard()
}

async function toggleMetadataPanePin() {
  metadataPanePinned.value = !metadataPanePinned.value
  metadataPane.value = true
  await loadSavedImages()
}

function closeMetadataPane() {
  metadataPanePinned.value = false
  metadataPane.value = false
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

async function useRecalledSettings() {
  await useSavedImageSettings(recalledMetadata.value, 'all')
}

function openSavedImageContextMenu(event, savedImage) {
  event.preventDefault()
  contextMenuSavedImage.value = savedImage
  savedImageContextMenuPosition.value = [event.clientX, event.clientY]
  savedImageContextMenu.value = false
  window.requestAnimationFrame(() => {
    savedImageContextMenu.value = true
  })
}

function toggleImageLibraryView() {
  imageLibraryView.value = imageLibraryView.value === 'thumbnails' ? 'list' : 'thumbnails'
}

function startImageLibraryResize(event) {
  if (mobile.value) return
  imageLibraryResizeStartX = event.clientX
  imageLibraryResizeStartWidth = imageLibraryWidth.value
  event.currentTarget.setPointerCapture(event.pointerId)
}

function resizeImageLibrary(event) {
  if (!event.currentTarget.hasPointerCapture(event.pointerId)) return
  const maximumWidth = Math.max(300, window.innerWidth - 320)
  imageLibraryWidth.value = Math.min(maximumWidth, Math.max(300, imageLibraryResizeStartWidth + imageLibraryResizeStartX - event.clientX))
}

function stopImageLibraryResize(event) {
  if (event.currentTarget.hasPointerCapture(event.pointerId)) event.currentTarget.releasePointerCapture(event.pointerId)
}

async function useSavedImageSettings(metadata, setting) {
  if (!metadata) return
  savedImageContextMenu.value = false

  if (setting === 'prompt' || setting === 'all') prompt.value = metadata.prompt
  if (setting === 'steps' || setting === 'all') steps.value = metadata.steps
  if (setting === 'seed' || setting === 'all') seed.value = metadata.seed ?? createRandomSeed()
  if ((setting === 'rotation' || setting === 'all') && rotationOptions.some(option => option.value === metadata.rotation)) {
    await setDisplayRotation(metadata.rotation)
  }
  if (setting === 'model' || setting === 'all') {
    const modelId = metadata.model?.id
    if (modelId && modelId !== activeModelId.value) selectModelById(modelId)
  }

  const settingLabel = setting === 'all' ? 'Saved image settings' : `Saved image ${setting}`
  status.value = `${settingLabel} restored to the generator.`
  page.value = 'generate'
  if (!metadataPanePinned.value) metadataPane.value = false
}

function animateSavedImage(savedImage) {
  if (!savedImage) return
  savedImageContextMenu.value = false
  videoSourceImage.value = savedImage
  videoPrompt.value = 'Subtle natural motion, gentle cinematic camera movement'
  page.value = 'video'
  if (!metadataPanePinned.value) metadataPane.value = false
}

function confirmDeleteSavedImage() {
  savedImageContextMenu.value = false
  if (contextMenuSavedImage.value) deleteSavedImageDialog.value = true
}

async function deleteSavedImage() {
  const savedImage = contextMenuSavedImage.value
  if (!savedImage || deletingSavedImage.value) return
  deletingSavedImage.value = true
  metadataError.value = ''
  try {
    const response = await fetch(`/saved-images/${encodeURIComponent(savedImage.id)}`, { method: 'DELETE' })
    if (!response.ok) {
      const body = await response.json().catch(() => ({}))
      throw new Error(body.detail || `Request failed (${response.status})`)
    }
    savedImages.value = savedImages.value.filter(image => image.id !== savedImage.id)
    if (recalledMetadata.value === savedImage.metadata) recalledMetadata.value = null
    deleteSavedImageDialog.value = false
    status.value = 'Image removed from the Creation Library.'
  } catch (requestError) {
    metadataError.value = `Could not remove this saved image: ${requestError.message}`
  } finally {
    deletingSavedImage.value = false
  }
}

async function openSavedImage(savedImage) {
  metadataError.value = ''
  try {
    const response = await fetch(`/saved-images/${encodeURIComponent(savedImage.id)}/image`)
    if (!response.ok) throw new Error(`Request failed (${response.status})`)
    const imageBlob = await response.blob()
    if (imageUrl.value) URL.revokeObjectURL(imageUrl.value)
    if (previewUrl.value) URL.revokeObjectURL(previewUrl.value)
    imageUrl.value = URL.createObjectURL(imageBlob)
    previewUrl.value = await createDisplayPreview(imageBlob)
    previewFittedFor.value = display.value?.connected ? display.value : null
    generatedMetadata.value = savedImage.metadata
    recalledMetadata.value = savedImage.metadata
    selectedSavedImage.value = savedImage
    currentImageSavedToLibrary.value = true
    if (display.value?.connected) {
      const displayResponse = await fetch(`/saved-images/${encodeURIComponent(savedImage.id)}/display`, { method: 'POST' })
      if (!displayResponse.ok) {
        const body = await displayResponse.json().catch(() => ({}))
        throw new Error(body.detail || `Could not send image to display (${displayResponse.status})`)
      }
      status.value = 'Selected image is ready for your ESP32 display.'
    }
  } catch (requestError) {
    metadataError.value = `Could not open this saved image: ${requestError.message}`
  }
}

async function saveCurrentImageToCreationLibrary() {
  if (!imageUrl.value || currentImageSavedToLibrary.value || savingToCreationLibrary.value) return
  savingToCreationLibrary.value = true
  error.value = ''
  try {
    const imageResponse = await fetch(imageUrl.value)
    if (!imageResponse.ok) throw new Error('Could not read the current image')
    const response = await fetch('/creation-library/images', {
      method: 'POST',
      headers: { 'Content-Type': 'image/jpeg' },
      body: await imageResponse.blob()
    })
    if (!response.ok) {
      const body = await response.json().catch(() => ({}))
      throw new Error(body.detail || `Request failed (${response.status})`)
    }
    currentImageSavedToLibrary.value = true
    await loadSavedImages()
    status.value = 'Image saved to your Creation Library.'
  } catch (requestError) {
    error.value = `Could not save the image to the Creation Library: ${requestError.message}`
  } finally {
    savingToCreationLibrary.value = false
  }
}

async function saveImageToDisplaySdCard(savedImage = null) {
  if (savingToDisplaySdCard.value) return
  savingToDisplaySdCard.value = true
  error.value = ''
  status.value = ''
  try {
    const endpoint = savedImage
      ? `/display-commands/save-saved-image/${encodeURIComponent(savedImage.id)}`
      : '/display-commands/save-latest'
    const response = await fetch(endpoint, { method: 'POST' })
    if (!response.ok) {
      const body = await response.json().catch(() => ({}))
      throw new Error(body.detail || `Request failed (${response.status})`)
    }
    const command = await response.json()
    if (command.status === 'already_saved') {
      status.value = command.detail || 'This image is already on the display SD card.'
      await loadDisplaySdCard()
      return
    }
    status.value = 'Save request sent to the display. Waiting for its SD card...'
    for (let attempt = 0; attempt < 15; attempt += 1) {
      await new Promise(resolve => window.setTimeout(resolve, 1000))
      const commandResponse = await fetch(`/display-commands/${encodeURIComponent(command.id)}`)
      if (!commandResponse.ok) continue
      const currentCommand = await commandResponse.json()
      if (currentCommand.status === 'complete') {
        status.value = `Saved to the display SD card: ${currentCommand.detail}`
        return
      }
      if (currentCommand.status === 'failed') throw new Error(currentCommand.detail || 'The display could not save the image')
    }
    status.value = 'Save request is pending. The display will save the image when it next connects.'
  } catch (requestError) {
    error.value = `Could not save to the display SD card: ${requestError.message}`
  } finally {
    savingToDisplaySdCard.value = false
  }
}

async function saveContextMenuImageToDisplaySdCard() {
  savedImageContextMenu.value = false
  await saveImageToDisplaySdCard(contextMenuSavedImage.value)
}

async function createDisplayPreview(blob) {
  const target = display.value?.connected ? display.value : null
  if (!target || typeof window.createImageBitmap !== 'function') {
    return URL.createObjectURL(blob)
  }

  const source = await window.createImageBitmap(blob)
  const canvas = document.createElement('canvas')
  canvas.width = target.width
  canvas.height = target.height
  const context = canvas.getContext('2d')
  if (!context) {
    source.close()
    return URL.createObjectURL(blob)
  }

  // Match ImageOps.fit on the server: fill the current display frame and
  // center-crop anything outside its aspect ratio.
  const scale = Math.max(canvas.width / source.width, canvas.height / source.height)
  const width = source.width * scale
  const height = source.height * scale
  context.drawImage(source, (canvas.width - width) / 2, (canvas.height - height) / 2, width, height)
  source.close()
  const previewBlob = await new Promise(resolve => canvas.toBlob(resolve, 'image/jpeg', 0.92))
  return URL.createObjectURL(previewBlob || blob)
}

function useRecommendedSteps() {
  const selectedModel = models.value.find(model => model.id === activeModelId.value)
  if (selectedModel) steps.value = selectedModel.default_steps
}

async function generate() {
  generating.value = true
  error.value = ''
  status.value = ''
  generationProgress.value = 0
  generationStage.value = 'Preparing image generation...'
  try {
    await prepareSelectedModel()
    generationStage.value = 'Starting image generation...'
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
      generationStage.value = currentJob.steps ? `${currentJob.stage} — Step ${currentJob.step} of ${currentJob.steps}` : currentJob.stage
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
    const imageBlob = rawImageBlob
    if (imageUrl.value) URL.revokeObjectURL(imageUrl.value)
    if (previewUrl.value) URL.revokeObjectURL(previewUrl.value)
    imageUrl.value = URL.createObjectURL(imageBlob)
    previewUrl.value = await createDisplayPreview(imageBlob)
    previewFittedFor.value = display.value?.connected ? display.value : null
    generatedMetadata.value = metadata
    selectedSavedImage.value = null
    currentImageSavedToLibrary.value = autoSaveImages.value
    await loadSavedImages()
    status.value = autoSaveImages.value
      ? 'Image ready and saved. Your ESP32 display will pick it up shortly.'
      : 'Image ready. Automatic saving is off—use Save image to computer to keep this image.'
  } catch (requestError) {
    if (requestError.message === 'Image generation cancelled.') {
      status.value = requestError.message
    } else {
      error.value = `Could not generate the image: ${requestError.message}`
      status.value = ''
    }
  } finally {
    generating.value = false
    cancelling.value = false
    activeJobId.value = ''
    generationProgress.value = 0
    generationStage.value = ''
  }
}

async function cancelGeneration() {
  if (cancelling.value) return
  cancelling.value = true
  error.value = ''
  if (modelSwitchAbortController) {
    generationStage.value = 'Cancelling model preparation...'
    modelSwitchAbortController.abort()
    return
  }
  if (!activeJobId.value) return
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

async function generateVideo() {
  if (generatingVideo.value) return
  generatingVideo.value = true
  videoError.value = ''
  videoProgress.value = 0
  videoStage.value = 'Starting video generation. LTX-Video will download first if it is not already on this computer...'
  try {
    const response = await fetch('/video-generation-jobs', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        prompt: videoPrompt.value,
        num_frames: Number(videoFrames.value),
        fps: Number(videoFps.value),
        steps: Number(videoSteps.value),
        seed: videoSeed.value === '' ? null : Number(videoSeed.value),
        source_image_id: videoSourceImage.value?.id || null
      })
    })
    if (!response.ok) {
      const body = await response.json().catch(() => ({}))
      throw new Error(body.detail || `Request failed (${response.status})`)
    }
    const job = await response.json()
    activeVideoJobId.value = job.id
    let currentJob = job
    while (!['complete', 'failed', 'cancelled'].includes(currentJob.status)) {
      await new Promise(resolve => window.setTimeout(resolve, 500))
      const statusResponse = await fetch(`/video-generation-jobs/${job.id}`)
      if (!statusResponse.ok) throw new Error(`Request failed (${statusResponse.status})`)
      currentJob = await statusResponse.json()
      videoProgress.value = currentJob.progress
      videoStage.value = currentJob.steps ? `${currentJob.stage} — Step ${currentJob.step} of ${currentJob.steps}` : currentJob.stage
    }
    if (currentJob.status === 'cancelled') {
      videoStage.value = 'Video generation cancelled.'
      return
    }
    if (currentJob.status === 'failed') throw new Error(currentJob.error || 'Video generation failed')
    const videoResponse = await fetch(`/video-generation-jobs/${job.id}/video`)
    if (!videoResponse.ok) throw new Error(`Request failed (${videoResponse.status})`)
    if (videoUrl.value) URL.revokeObjectURL(videoUrl.value)
    videoUrl.value = URL.createObjectURL(await videoResponse.blob())
    videoStage.value = 'Video ready. It is saved locally and can be downloaded below.'
  } catch (requestError) {
    videoError.value = `Could not generate the video: ${requestError.message}`
    videoStage.value = ''
  } finally {
    generatingVideo.value = false
    cancellingVideo.value = false
    activeVideoJobId.value = ''
  }
}

async function cancelVideoGeneration() {
  if (cancellingVideo.value || !activeVideoJobId.value) return
  cancellingVideo.value = true
  try {
    const response = await fetch(`/video-generation-jobs/${activeVideoJobId.value}`, { method: 'DELETE' })
    if (!response.ok) throw new Error(`Request failed (${response.status})`)
  } catch (requestError) {
    cancellingVideo.value = false
    videoError.value = `Could not cancel video generation: ${requestError.message}`
  }
}

onMounted(async () => {
  await loadServerStatus()
  await loadDisplay()
  await loadDisplaySettings()
  await loadModels()
  await loadSavedImages()
  await loadAppSettings()
  if (metadataPanePinned.value && !mobile.value) metadataPane.value = true
  statusTimer = window.setInterval(() => {
    loadServerStatus()
    loadDisplay()
    loadModels()
    loadDisplaySdCard()
  }, 5000)
})

onUnmounted(() => {
  window.clearInterval(statusTimer)
  modelSwitchAbortController?.abort()
  if (imageUrl.value) URL.revokeObjectURL(imageUrl.value)
  if (previewUrl.value) URL.revokeObjectURL(previewUrl.value)
  if (videoUrl.value) URL.revokeObjectURL(videoUrl.value)
})
</script>

<template>
  <v-app>
    <v-snackbar v-model="displayConnectedSnackbar" color="success" location="top" timeout="5000">
      <div class="d-flex align-center ga-2">
        <v-icon icon="mdi-monitor-check" />
        <span>{{ displayConnectedMessage }}</span>
      </div>
      <template #actions>
        <v-btn variant="text" @click="displayConnectedSnackbar = false">Close</v-btn>
      </template>
    </v-snackbar>
    <v-snackbar v-model="sdCardSnackbar" color="success" location="bottom" timeout="3500">
      <div class="d-flex align-center ga-2">
        <v-icon icon="mdi-check-circle" />
        <span>{{ sdCardSnackbarMessage }}</span>
      </div>
    </v-snackbar>

    <v-app-bar color="surface" border elevation="2" class="app-bar">
      <v-app-bar-nav-icon aria-label="Toggle navigation" @click="drawer = !drawer" />
      <v-avatar :image="logoImageUrl" size="36" class="mr-3" />
      <div class="app-bar__brand mr-4">
        <span class="font-weight-bold">ESPImageServer</span>
        <span v-if="serverInfo?.version" class="text-caption text-medium-emphasis">v{{ serverInfo.version }}</span>
      </div>
      <v-chip class="mr-2" :color="health?.status === 'ready' ? 'success' : 'warning'" variant="tonal" prepend-icon="mdi-server">
        {{ health?.status === 'ready' ? 'Server ready' : 'Server loading' }}
      </v-chip>
      <v-chip :color="display?.connected ? 'info' : 'warning'" variant="tonal" prepend-icon="mdi-monitor-dashboard">
        {{ display?.connected ? `${display.name} · ${display.width}×${display.height}` : 'Display waiting' }}
      </v-chip>
      <v-spacer />
      <v-btn size="x-large" icon="mdi-image-text" variant="text" aria-label="Open Creation Library" title="Open Creation Library" @click="openMetadataPane" />
    </v-app-bar>

    <v-navigation-drawer v-model="drawer" width="272" border :temporary="mobile">
      <v-list-item class="py-4" title="ESPImageServer" subtitle="Local AI image generation" />
      <v-divider />
      <v-list nav density="comfortable">
        <v-list-item title="Generate image" :active="page === 'generate'" @click="openGeneratePage">
          <template #prepend>
            <v-avatar :image="logoImageUrl" size="26" />
          </template>
        </v-list-item>
        <v-list-item prepend-icon="mdi-movie-open-outline" title="Generate video" :active="page === 'video'" @click="page = 'video'" />
        <v-list-item prepend-icon="mdi-brain" title="Models" :active="page === 'models'" @click="page = 'models'" />
        <v-list-item prepend-icon="mdi-sd" title="SD Card" :active="page === 'sd-card'" @click="openSDCardPage" />
        <v-list-item prepend-icon="mdi-cog-outline" title="Settings" :active="page === 'settings'" @click="page = 'settings'" />
        <v-list-item prepend-icon="mdi-information-outline" title="About" :active="page === 'about'" @click="page = 'about'" />
      </v-list>
      <template #append>
        <div class="pa-4 text-caption text-medium-emphasis">Images stay on your local network.</div>
      </template>
    </v-navigation-drawer>

    <v-navigation-drawer v-model="metadataPane" location="right" :width="imageLibraryWidth" :permanent="metadataPanePinned && !mobile" :temporary="!metadataPanePinned || mobile" border>
      <div
        v-if="!mobile"
        class="image-library-resize-handle"
        role="separator"
        aria-label="Resize Creation Library"
        aria-orientation="vertical"
        @pointerdown="startImageLibraryResize"
        @pointermove="resizeImageLibrary"
        @pointerup="stopImageLibraryResize"
        @pointercancel="stopImageLibraryResize"
      />
      <div class="d-flex align-center pa-4">
        <div>
          <div class="text-h6">Creation Library</div>
          <div class="text-caption text-medium-emphasis">Browse saved creations and restore their generation settings.</div>
        </div>
        <v-spacer />
        <v-btn
          :icon="imageLibraryView === 'thumbnails' ? 'mdi-format-list-bulleted' : 'mdi-view-grid'"
          variant="text"
          :aria-label="imageLibraryView === 'thumbnails' ? 'Use list view' : 'Use thumbnail view'"
          :title="imageLibraryView === 'thumbnails' ? 'Use list view' : 'Use thumbnail view'"
          @click="toggleImageLibraryView"
        />
        <v-btn :icon="metadataPanePinned ? 'mdi-pin' : 'mdi-pin-outline'" variant="text" :aria-label="metadataPanePinned ? 'Unpin image library pane' : 'Pin image library pane'" @click="toggleMetadataPanePin" />
        <v-btn icon="mdi-close" variant="text" aria-label="Close Creation Library" @click="closeMetadataPane" />
      </div>
      <v-divider />
      <div class="pa-4">
        <v-slider
          v-if="imageLibraryView === 'thumbnails'"
          v-model="imageLibraryThumbnailSize"
          min="100"
          max="220"
          step="10"
          hide-details
          density="compact"
          color="primary"
          prepend-icon="mdi-image-size-select-small"
          append-icon="mdi-image-size-select-large"
          aria-label="Thumbnail size"
          class="mb-5"
        />
        <div class="text-subtitle-1 font-weight-bold mb-2">Saved creations</div>
        <v-progress-linear v-if="savedImagesLoading" indeterminate color="primary" class="mb-3" />
        <div v-if="!savedImagesLoading && savedImages.length && imageLibraryView === 'thumbnails'" class="saved-image-library">
          <section v-for="group in savedImageGroups" :key="group.modelName" class="saved-image-group">
            <div class="text-caption font-weight-bold text-medium-emphasis mb-2">{{ group.modelName }}</div>
            <div class="saved-image-grid" :style="{ '--thumbnail-size': `${imageLibraryThumbnailSize}px` }">
              <v-tooltip v-for="savedImage in group.images" :key="savedImage.id" location="end" max-width="300">
                <template #activator="{ props }">
                  <v-card v-bind="props" class="saved-image-thumbnail" variant="outlined" @click="openSavedImage(savedImage)" @contextmenu="openSavedImageContextMenu($event, savedImage)">
                    <v-img :src="`/saved-images/${encodeURIComponent(savedImage.id)}/thumbnail`" aspect-ratio="1.33" cover />
                    <div class="pa-2 text-caption saved-image-thumbnail__prompt">{{ savedImage.metadata?.prompt || 'Generated image' }}</div>
                  </v-card>
                </template>
                <div class="text-body-2">
                  <div><strong>Model:</strong> {{ savedImage.metadata?.model?.name || 'ESPImageServer' }}</div>
                  <div class="mt-1"><strong>Prompt:</strong> {{ savedImage.metadata?.prompt || 'Generated image' }}</div>
                  <div class="mt-1"><strong>Steps:</strong> {{ savedImage.metadata?.steps ?? '—' }}</div>
                  <div><strong>Seed:</strong> {{ savedImage.metadata?.seed ?? 'Random seed' }}</div>
                  <div><strong>Rotation:</strong> {{ savedImage.metadata?.rotation || 0 }}°</div>
                  <div><strong>Created:</strong> {{ formatDateTime(savedImage.created_at) }}</div>
                </div>
              </v-tooltip>
            </div>
          </section>
        </div>
        <v-list v-if="!savedImagesLoading && savedImages.length && imageLibraryView === 'list'" class="saved-image-library saved-image-list" density="compact" lines="two">
          <v-list-item v-for="savedImage in savedImages" :key="savedImage.id" prepend-icon="mdi-image" @click="openSavedImage(savedImage)" @contextmenu="openSavedImageContextMenu($event, savedImage)">
            <v-list-item-title>{{ savedImage.metadata?.prompt || 'Generated image' }}</v-list-item-title>
            <v-list-item-subtitle>{{ savedImage.metadata?.model?.name || 'ESPImageServer' }} · {{ new Date(savedImage.created_at).toLocaleString() }}</v-list-item-subtitle>
          </v-list-item>
        </v-list>
        <div v-if="!savedImagesLoading && !savedImages.length" class="text-body-2 text-medium-emphasis">No generated images have been saved yet.</div>
        <v-alert v-if="metadataError" type="warning" variant="tonal" density="compact" class="mt-3">{{ metadataError }}</v-alert>
      </div>
    </v-navigation-drawer>

    <v-menu
      v-model="savedImageContextMenu"
      :target="savedImageContextMenuPosition"
      location="bottom start"
      :close-on-content-click="true"
    >
      <v-list min-width="220" density="comfortable">
        <v-list-subheader>Reuse generation settings</v-list-subheader>
        <v-list-item prepend-icon="mdi-text" title="Use prompt" :disabled="generationBusy" @click="useSavedImageSettings(contextMenuSavedImage?.metadata, 'prompt')" />
        <v-list-item prepend-icon="mdi-dice-5" title="Use seed" :disabled="generationBusy" @click="useSavedImageSettings(contextMenuSavedImage?.metadata, 'seed')" />
        <v-list-item prepend-icon="mdi-foot-print" title="Use steps" :disabled="generationBusy" @click="useSavedImageSettings(contextMenuSavedImage?.metadata, 'steps')" />
        <v-list-item prepend-icon="mdi-brain" title="Use model" :disabled="generationBusy" @click="useSavedImageSettings(contextMenuSavedImage?.metadata, 'model')" />
        <v-list-item prepend-icon="mdi-rotate-right" title="Use rotation" :disabled="generationBusy" @click="useSavedImageSettings(contextMenuSavedImage?.metadata, 'rotation')" />
        <v-divider class="my-1" />
        <v-list-item color="primary" prepend-icon="mdi-restore" title="Use all" :disabled="generationBusy" @click="useSavedImageSettings(contextMenuSavedImage?.metadata, 'all')" />
        <v-list-item color="primary" prepend-icon="mdi-sd" title="Save to display SD card" :disabled="!display?.connected || savingToDisplaySdCard" @click="saveContextMenuImageToDisplaySdCard" />
        <v-list-item color="primary" prepend-icon="mdi-movie-open-plus" title="Animate as video" :disabled="health?.device !== 'cuda'" @click="animateSavedImage(contextMenuSavedImage)" />
        <v-divider class="my-1" />
        <v-list-item color="error" prepend-icon="mdi-delete-outline" title="Delete from Creation Library" @click="confirmDeleteSavedImage" />
      </v-list>
    </v-menu>

    <v-dialog v-model="deleteSavedImageDialog" max-width="440" width="calc(100% - 32px)">
      <v-card title="Delete saved image">
        <v-card-text>
          Remove this image from the Creation Library? This cannot be undone.
        </v-card-text>
        <v-card-actions class="px-6 pb-5">
          <v-spacer />
          <v-btn variant="text" :disabled="deletingSavedImage" @click="deleteSavedImageDialog = false">Keep image</v-btn>
          <v-btn color="error" variant="flat" :loading="deletingSavedImage" @click="deleteSavedImage">Delete image</v-btn>
        </v-card-actions>
      </v-card>
    </v-dialog>

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
              <v-alert
                :icon="health?.device === 'cuda' ? 'mdi-expansion-card-variant' : 'mdi-cpu-64-bit'"
                :type="health?.device === 'cuda' ? 'success' : 'info'"
                variant="tonal"
                density="compact"
                class="mb-4"
              >
                <strong>Image processing:</strong> {{ serverInfo?.processing || 'Loading processing information...' }}
              </v-alert>
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
              <v-switch
                :model-value="autoSaveImages"
                label="Save generated images automatically"
                color="primary"
                :loading="autoSaveSaving"
                :disabled="generationBusy || autoSaveSaving"
                hint="When off, images still reach your ESP32, but are not added to the Creation Library."
                persistent-hint
                class="mb-4"
                @update:model-value="setAutoSaveImages"
              />
              <v-textarea
                v-model="prompt"
                label="Describe an image"
                maxlength="1000"
                counter="1000"
                required
                variant="outlined"
                rows="4"
                auto-grow
                max-rows="12"
              />
              <v-alert type="info" variant="tonal" density="compact" class="mb-4">
                <strong>Steps</strong> trade speed for detail: more steps take longer. <strong>Seed</strong> lets you repeat a result. Use Create random seed for a fresh image variation.
              </v-alert>
              <v-row dense class="mb-6">
                <v-col cols="12" sm="6">
                  <v-text-field v-model.number="steps" label="Generation steps" type="number" :min="models.find(model => model.id === activeModelId)?.minimum_steps" :max="models.find(model => model.id === activeModelId)?.maximum_steps" variant="outlined" density="comfortable" hint="More steps can improve detail. Use the reset icon for this model's recommendation." persistent-hint append-inner-icon="mdi-restore" @click:append-inner="useRecommendedSteps" />
                </v-col>
                <v-col cols="12" sm="6">
                  <v-text-field v-model="seed" label="Seed" type="number" min="0" max="4294967295" variant="outlined" density="comfortable" hint="Use the same seed to reproduce an image." persistent-hint append-inner-icon="mdi-dice-5" @click:append-inner="chooseRandomSeed" />
                  <v-btn class="mt-1" size="small" variant="text" prepend-icon="mdi-dice-5" @click="chooseRandomSeed">Create random seed</v-btn>
                </v-col>
              </v-row>
              <v-btn type="submit" color="primary" :disabled="generationBusy" prepend-icon="mdi-image-plus">
                Generate image
              </v-btn>
              <v-btn v-if="generating" class="ml-2" color="warning" variant="tonal" :loading="cancelling" :disabled="cancelling" prepend-icon="mdi-cancel" @click="cancelGeneration">
                {{ activeJobId ? 'Cancel generation' : 'Cancel' }}
              </v-btn>
              <div v-if="generating" class="mt-5">
                <div class="d-flex justify-space-between text-body-2 mb-2">
                  <span>{{ generationStage }}</span><span>{{ activeJobId ? `${generationProgress}%` : 'Preparing' }}</span>
                </div>
                <v-progress-linear :model-value="generationProgress" :indeterminate="!activeJobId" color="primary" height="10" rounded />
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
          <v-img v-if="previewUrl" :src="previewUrl" alt="Image fitted to the connected ESP32 display" />
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
            <v-chip v-if="previewFittedFor" size="small" variant="tonal" prepend-icon="mdi-monitor-dashboard">
              Preview: fitted for {{ previewFittedFor.name }} ({{ previewFittedFor.width }}×{{ previewFittedFor.height }})
            </v-chip>
            <v-btn :href="imageUrl" download="esp-image.jpg" color="secondary" prepend-icon="mdi-download">
              Download JPEG
            </v-btn>
            <v-btn color="primary" variant="tonal" prepend-icon="mdi-sd" :loading="savingToDisplaySdCard" :disabled="!display?.connected" @click="saveImageToDisplaySdCard(selectedSavedImage)">
              Save to display SD card
            </v-btn>
            <v-btn variant="text" prepend-icon="mdi-image-text" @click="openMetadataPane">Creation Library</v-btn>
          </v-card-actions>
          <v-alert v-if="imageUrl && !autoSaveImages" type="warning" variant="tonal" class="mx-4 mb-4" density="comfortable" icon="mdi-content-save-alert">
            <div class="font-weight-medium">This image is not saved in your Creation Library.</div>
            <div class="text-body-2 mt-1">Automatic saving is off. Save this creation to keep its image and generation details in the app.</div>
            <template #append>
              <v-btn color="warning" variant="flat" prepend-icon="mdi-bookmark-plus" :loading="savingToCreationLibrary" @click="saveCurrentImageToCreationLibrary">Save to Creation Library</v-btn>
            </template>
          </v-alert>
        </v-card>
        </v-col>
        </v-row>
        </template>

        <v-card v-else-if="page === 'video'" class="mx-auto" max-width="1400">
          <v-card-title class="text-h5 pt-5">Generate video <v-chip class="ml-2" size="small" color="warning" variant="tonal">Experimental</v-chip></v-card-title>
          <v-card-text>
            <v-alert type="warning" variant="tonal" density="compact" class="mb-4" icon="mdi-expansion-card-variant">
              LTX-Video 2B distilled requires a compatible NVIDIA GPU. The first video downloads the model and can take several minutes.
            </v-alert>
            <v-alert v-if="health?.device !== 'cuda'" type="error" variant="tonal" density="compact" class="mb-4" icon="mdi-cpu-64-bit">
              Video generation cannot run in CPU mode. Re-run the installer and choose <strong>NVIDIA CUDA acceleration</strong>, then restart ESPImageServer.
            </v-alert>
            <v-row>
              <v-col cols="12" lg="5">
            <v-form @submit.prevent="generateVideo">
              <div v-if="display?.connected" class="text-caption text-medium-emphasis mb-3">Video will be created at your connected display’s native size: {{ display.width }} × {{ display.height }}.</div>
              <v-alert v-if="videoSourceImage" type="success" variant="tonal" density="compact" class="mb-4">
                <div class="d-flex align-center">
                  <v-avatar rounded size="44" class="mr-3"><v-img :src="`/saved-images/${encodeURIComponent(videoSourceImage.id)}/thumbnail`" /></v-avatar>
                  <span>Animating the selected Creation Gallery image as the first frame.</span>
                  <v-spacer /><v-btn icon="mdi-close" size="small" variant="text" aria-label="Stop using this image for the video" @click="videoSourceImage = null" />
                </div>
              </v-alert>
              <v-textarea v-model="videoPrompt" label="Describe the video" hint="For best results, specify the subject, setting, lighting, camera shot, and one simple movement." persistent-hint maxlength="1000" counter="1000" required variant="outlined" rows="4" auto-grow />
              <v-row dense class="mt-1">
                <v-col cols="12" sm="6"><v-select v-model="videoFrames" label="Length" variant="outlined" density="comfortable" :items="videoFrameOptions" hint="Longer clips need more graphics-card memory." persistent-hint /></v-col>
                <v-col cols="12" sm="6"><v-select v-model="videoFps" label="Frames per second" variant="outlined" density="comfortable" :items="[8, 12, 15, 24]" /></v-col>
                <v-col cols="12" sm="6"><v-select v-model="videoSteps" label="Generation steps" variant="outlined" density="comfortable" hint="8 is recommended for the distilled model." persistent-hint :items="[4, 5, 6, 7, 8]" /></v-col>
                <v-col cols="12" sm="6"><v-text-field v-model="videoSeed" label="Seed" type="number" min="0" max="4294967295" variant="outlined" density="comfortable" append-inner-icon="mdi-dice-5" @click:append-inner="videoSeed = createRandomSeed()" /></v-col>
              </v-row>
              <v-btn type="submit" class="mt-4" color="primary" :disabled="generatingVideo || health?.device !== 'cuda'" prepend-icon="mdi-movie-open-plus">Generate video</v-btn>
              <v-btn v-if="generatingVideo" class="ml-2 mt-4" color="warning" variant="tonal" :loading="cancellingVideo" @click="cancelVideoGeneration">Cancel</v-btn>
            </v-form>
            <div v-if="generatingVideo" class="mt-5">
              <div class="d-flex justify-space-between text-body-2 mb-2"><span>{{ videoStage }}</span><span>{{ videoProgress }}%</span></div>
              <v-progress-linear :model-value="videoProgress" :indeterminate="!activeVideoJobId" color="primary" height="10" rounded />
            </div>
            <v-alert v-else-if="videoStage" type="success" variant="tonal" density="compact" class="mt-4">{{ videoStage }}</v-alert>
            <v-alert v-if="videoError" type="error" variant="tonal" density="compact" class="mt-4">{{ videoError }}</v-alert>
              </v-col>
              <v-col cols="12" lg="7">
                <v-card class="generated-video-card h-100">
                  <video v-if="videoUrl" :src="videoUrl" controls loop class="w-100 rounded" />
                  <v-sheet v-else class="preview-placeholder d-flex flex-column align-center justify-center text-center pa-8">
                    <v-avatar color="primary" variant="tonal" size="64" class="mb-4"><v-icon size="34">mdi-movie-open-outline</v-icon></v-avatar>
                    <div class="text-h6">Your generated video will appear here</div>
                    <div class="text-body-2 text-medium-emphasis mt-2">Describe a scene, choose your settings, then select Generate video.</div>
                  </v-sheet>
                </v-card>
              </v-col>
            </v-row>
          </v-card-text>
          <v-card-actions v-if="videoUrl"><v-btn :href="videoUrl" download="esp-image-video.mp4" color="secondary" prepend-icon="mdi-download">Download MP4</v-btn></v-card-actions>
        </v-card>

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
                    {{ model.installed ? 'Downloaded' : 'Downloads when selected' }}
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

        <v-card v-else-if="page === 'about'">
          <v-card-title>About ESPImageServer</v-card-title>
          <v-card-text class="text-body-1">
            Generate local AI images and show them on a connected ESP32 display. Images remain on your local network.
          </v-card-text>
          <v-list density="compact">
            <v-list-item prepend-icon="mdi-tag-outline" title="App version" :subtitle="serverInfo?.version ? `Version ${serverInfo.version}` : 'Loading version information...'" />
            <v-list-item prepend-icon="mdi-brain" title="Model" :subtitle="serverInfo?.model_description || 'Loading model information...'" />
            <v-list-item
              :prepend-icon="health?.device === 'cuda' ? 'mdi-expansion-card-variant' : 'mdi-cpu-64-bit'"
              title="Image processing"
              :subtitle="serverInfo?.processing || 'Loading processing information...'"
            />
            <v-list-item prepend-icon="mdi-monitor-dashboard" title="Display" :subtitle="displayMessage" />
          </v-list>
        </v-card>

        <v-card v-else-if="page === 'sd-card'">
          <v-card-title class="d-flex align-center text-h5 pt-5">
            Display SD Card
            <v-spacer />
            <v-chip v-if="displaySdCard.available" color="success" size="small" variant="tonal" prepend-icon="mdi-sd">
              Card ready · {{ displaySdCard.files?.length || 0 }} images
            </v-chip>
          </v-card-title>
          <v-card-text>
            <v-alert v-if="!displaySdCard.available" type="warning" variant="tonal" density="compact" class="mb-4">
              Waiting for the display to report its SD card.
            </v-alert>
            <v-alert v-if="error" type="error" variant="tonal" density="compact" class="mb-4">{{ error }}</v-alert>
            <div class="d-flex flex-wrap ga-2 mb-4">
              <v-btn prepend-icon="mdi-refresh" :loading="displaySdCardLoading" @click="loadDisplaySdCard">Refresh</v-btn>
            </div>
            <v-data-table
              :headers="sdCardTableHeaders"
              :items="displaySdCard.files || []"
              :loading="displaySdCardLoading"
              :items-per-page="10"
              hover
              density="comfortable"
              class="sd-card-table border rounded"
            >
              <template #item.thumbnail="{ item }">
                <v-avatar v-if="item.thumbnail_available" rounded="sm" size="56">
                  <v-img :src="`/display-sd-card/thumbnails/${encodeURIComponent(item.name)}`" cover />
                </v-avatar>
                <v-avatar v-else color="surface-variant" rounded="sm" size="56">
                  <v-icon>mdi-image-outline</v-icon>
                </v-avatar>
              </template>
              <template #item.name="{ item }">
                <div class="font-weight-medium">{{ item.name }}</div>
                <div class="text-caption text-medium-emphasis">Saved on your display SD card</div>
              </template>
              <template #item.size="{ item }">{{ formatFileSize(item.size) }}</template>
              <template #item.created_at="{ item }">{{ formatDateTime(item.created_at) }}</template>
              <template #item.actions="{ item }">
                <div class="d-flex justify-end ga-1">
                  <v-tooltip text="Show on display">
                    <template #activator="{ props }">
                      <v-btn v-if="displayingSdCardFile !== item.name" v-bind="props" icon="mdi-play" size="small" color="primary" variant="text" :disabled="Boolean(displayingSdCardFile)" @click="showSDCardFileOnDisplay(item.name)" />
                      <v-progress-circular v-else v-bind="props" indeterminate color="primary" size="22" width="3" />
                    </template>
                  </v-tooltip>
                  <v-tooltip text="Delete from SD card">
                    <template #activator="{ props }">
                      <v-btn v-bind="props" icon="mdi-delete-outline" size="small" color="error" variant="text" :disabled="Boolean(displayingSdCardFile)" @click="sendDisplaySdCardCommand(`/display-sd-card/files/${encodeURIComponent(item.name)}`, 'DELETE')" />
                    </template>
                  </v-tooltip>
                </div>
              </template>
              <template #no-data>
                <div class="py-8 text-center text-medium-emphasis">No saved SD card images yet.</div>
              </template>
            </v-data-table>
          </v-card-text>
        </v-card>

        <v-card v-else class="settings-card">
          <v-card-title class="text-h5 pt-5">Settings</v-card-title>
          <v-card-text>
            <v-form @submit.prevent="saveAppSettings">
              <v-text-field
                v-model="imageLibraryLocation"
                label="Image library location"
                variant="outlined"
                readonly
                hint="Existing generated images move with the library. Choose an empty destination folder."
                persistent-hint
                prepend-inner-icon="mdi-folder-image"
                class="mb-7"
              />
              <v-btn type="button" class="mb-3 mr-2" variant="tonal" prepend-icon="mdi-folder-search" :loading="choosingImageLibrary" @click="chooseImageLibrary">
                Choose image library folder
              </v-btn>
              <v-btn type="button" class="mb-6" variant="tonal" prepend-icon="mdi-folder-open" :loading="openingImageLibrary" @click="revealImageLibrary">
                Open image library folder
              </v-btn>
              <v-slider
                v-model="jpegQuality"
                label="JPEG quality"
                min="40"
                max="100"
                step="5"
                thumb-label
                color="primary"
                class="mt-2"
              />
              <div class="text-body-2 text-medium-emphasis mb-5">
                Higher quality produces larger files and can take a little longer for the ESP32 to download. This applies to newly generated images only.
              </div>
              <v-btn type="submit" color="primary" :loading="settingsSaving" prepend-icon="mdi-content-save">Save settings</v-btn>
              <v-alert v-if="settingsStatus" type="success" variant="tonal" density="compact" class="mt-4">{{ settingsStatus }}</v-alert>
              <v-alert v-if="settingsError" type="error" variant="tonal" density="compact" class="mt-4">{{ settingsError }}</v-alert>
            </v-form>
          </v-card-text>
        </v-card>
      </v-container>
    </v-main>
  </v-app>
</template>
