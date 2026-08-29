<script setup>
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from 'vue'
import { useDisplay } from 'vuetify'
import QRCode from 'qrcode'

function createRandomSeed() {
  return Math.floor(Math.random() * 4_294_967_296)
}

const generationSettingsKey = 'esp-image-server.generation-settings'
const videoGenerationSettingsKey = 'esp-image-server.video-generation-settings'
const imageLibraryPaneSettingsKey = 'esp-image-server.image-library-pane-pinned'
const imageLibraryViewSettingsKey = 'esp-image-server.image-library-view'
const imageLibraryWidthSettingsKey = 'esp-image-server.image-library-width'
const imageLibraryThumbnailSizeSettingsKey = 'esp-image-server.image-library-thumbnail-size'
const sdCardItemsPerPageSettingsKey = 'esp-image-server.sd-card-items-per-page'
const activeDisplaySettingsKey = 'esp-image-server.active-display-id'
const mobileAccessPromptDismissedSettingsKey = 'esp-image-server.mobile-access-prompt-dismissed'
const videoModelIds = ['ltx-2b-0.9.6-distilled', 'ltx-2b-0.9.6-dev', 'wan-2.1-t2v-1.3b', 'hunyuanvideo-1.5-480p']

function loadImageLibraryWidth() {
  const savedWidth = Number(window.localStorage.getItem(imageLibraryWidthSettingsKey))
  return Number.isFinite(savedWidth) && savedWidth >= 300 && savedWidth <= 720 ? savedWidth : 380
}

function loadImageLibraryThumbnailSize() {
  const savedSize = Number(window.localStorage.getItem(imageLibraryThumbnailSizeSettingsKey))
  return Number.isFinite(savedSize) && savedSize >= 100 && savedSize <= 220 ? savedSize : 160
}

function loadSDCardItemsPerPage() {
  const savedValue = Number(window.localStorage.getItem(sdCardItemsPerPageSettingsKey))
  return Number.isInteger(savedValue) && savedValue >= 1 && savedValue <= 100 ? savedValue : 10
}

function loadGenerationSettings() {
  try {
    const saved = JSON.parse(window.localStorage.getItem(generationSettingsKey) || '{}')
    return {
      prompt: typeof saved.prompt === 'string' ? saved.prompt : 'A cheerful small robot holding a paintbrush, friendly illustration',
      steps: Number.isInteger(saved.steps) ? saved.steps : 1,
      seed: Number.isInteger(saved.seed) ? saved.seed : createRandomSeed(),
      negativePrompt: typeof saved.negativePrompt === 'string' ? saved.negativePrompt : '',
      modelId: typeof saved.modelId === 'string' ? saved.modelId : ''
    }
  } catch {
    return { prompt: 'A cheerful small robot holding a paintbrush, friendly illustration', steps: 1, seed: createRandomSeed(), negativePrompt: '', modelId: '' }
  }
}

function loadVideoGenerationSettings() {
  try {
    const saved = JSON.parse(window.localStorage.getItem(videoGenerationSettingsKey) || '{}')
    const modelId = videoModelIds.includes(saved.modelId) ? saved.modelId : 'ltx-2b-0.9.6-distilled'
    const validSteps = modelId === 'ltx-2b-0.9.6-dev'
      ? [10, 15, 20, 25, 30, 35, 40]
      : modelId === 'wan-2.1-t2v-1.3b' || modelId === 'hunyuanvideo-1.5-480p'
        ? [20, 25, 30, 35, 40, 45, 50]
        : [4, 5, 6, 7, 8]
    return {
      prompt: typeof saved.prompt === 'string' ? saved.prompt : 'Gentle cinematic camera movement, subtle natural motion',
      frames: Number.isInteger(saved.frames) && saved.frames >= 9 && saved.frames <= 249 && (saved.frames - 1) % 8 === 0 ? saved.frames : 25,
      fps: [8, 12, 15, 24].includes(saved.fps) ? saved.fps : 8,
      steps: validSteps.includes(saved.steps) ? saved.steps : modelId === 'ltx-2b-0.9.6-distilled' ? 8 : 30,
      modelId,
      seed: Number.isInteger(saved.seed) ? saved.seed : createRandomSeed()
    }
  } catch {
    return { prompt: 'Gentle cinematic camera movement, subtle natural motion', frames: 25, fps: 8, steps: 8, modelId: 'ltx-2b-0.9.6-distilled', seed: createRandomSeed() }
  }
}

const savedGenerationSettings = loadGenerationSettings()
const savedVideoGenerationSettings = loadVideoGenerationSettings()
const prompt = ref(savedGenerationSettings.prompt)
const negativePrompt = ref(savedGenerationSettings.negativePrompt)
const serverInfo = ref(null)
const health = ref(null)
const displays = ref([])
const activeDisplayId = ref(window.localStorage.getItem(activeDisplaySettingsKey) || '')
const displayPickerOpen = ref(false)
const legacyDisplay = ref(null)
const displayConnectedSnackbar = ref(false)
const displayConnectedMessage = ref('')
const generationQueueSnackbar = ref(false)
const generationQueueSnackbarMessage = ref('')
const displayRotation = ref(0)
const videoRotation = ref(0)
const models = ref([])
const availableVideoModels = ref([])
const removingImageModelId = ref('')
const removeImageModelDialog = ref(false)
const imageModelToRemove = ref(null)
const removingVideoModelId = ref('')
const removeVideoModelDialog = ref(false)
const videoModelToRemove = ref(null)
const status = ref('')
const error = ref('')
const imageUrl = ref('')
const videoUrl = ref('')
const completedVideoJobId = ref('')
const completedVideoSavedId = ref('')
const savingVideoToCreationLibrary = ref(false)
const videoSavedToCreationLibrary = ref(false)
const savedVideos = ref([])
const savedVideoContextMenu = ref(false)
const savedVideoContextMenuPosition = ref([0, 0])
const contextMenuSavedVideo = ref(null)
const savingVideoToDisplaySdCard = ref(false)
const showingVideoOnDisplay = ref(false)
const videoSourceImage = ref(null)
const videoPrompt = ref(savedVideoGenerationSettings.prompt)
const videoSeed = ref(savedVideoGenerationSettings.seed)
const videoFrames = ref(savedVideoGenerationSettings.frames)
const videoFps = ref(savedVideoGenerationSettings.fps)
const videoDurationPresetSeconds = ref(null)
const showAdvancedVideoFrames = ref(false)
const videoSteps = ref(savedVideoGenerationSettings.steps)
const videoModelId = ref(savedVideoGenerationSettings.modelId)
const generatingVideo = ref(false)
const cancellingVideo = ref(false)
const cancelVideoOnStart = ref(false)
const activeVideoJobId = ref('')
const activeVideoJobRunning = ref(false)
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
const deleteSavedImageDontAskAgain = ref(false)
const deleteSavedVideoDialog = ref(false)
const deletingSavedVideo = ref(false)
const deleteSavedVideoDontAskAgain = ref(false)
const deleteSdCardFileDialog = ref(false)
const deletingSdCardFile = ref(false)
const deleteSdCardFileDontAskAgain = ref(false)
const sdCardFileToDelete = ref(null)
const deleteSdCardFilesDialog = ref(false)
const deletingSdCardFiles = ref(false)
const deleteSdCardFilesDontAskAgain = ref(false)
const selectedSdCardFileNames = ref([])
const sdCardFilesToDelete = ref([])
const savingToDisplaySdCard = ref(false)
const showingSavedImageOnDisplay = ref(false)
const displaySdCard = ref({ available: false, files: [] })
const displaySdCardLoading = ref(false)
const sdCardItemsPerPage = ref(loadSDCardItemsPerPage())
const displayExperience = ref({ current_mode: 'server_controlled', offline_experience: 'slideshow', slideshow_interval_ms: 15000, slideshow_order: 'newest_first' })
const displayExperienceIntervalSeconds = ref(15)
const displayExperienceLoading = ref(false)
const displayExperienceSaving = ref(false)
const displayExperiencePreviewing = ref(false)
const displayExperienceError = ref('')
const displayExperienceStatus = ref('')
const displayingSdCardFile = ref('')
const sdCardSnackbar = ref(false)
const sdCardSnackbarMessage = ref('')
const metadataError = ref('')
const savedImages = ref([])
const savedImagesLoading = ref(false)
const creationModelFilter = ref(null)
const creationDisplayFilter = ref(null)
const creationSdCardFilter = ref(null)
const imageLibraryLocation = ref('')
const jpegQuality = ref(85)
const videoJpegQuality = ref(10)
const autoSaveImages = ref(true)
const autoSaveVideos = ref(true)
const confirmDeletion = ref(true)
const autoSaveSaving = ref(false)
const autoSaveVideoSaving = ref(false)
const settingsSaving = ref(false)
const openingImageLibrary = ref(false)
const choosingImageLibrary = ref(false)
const settingsStatus = ref('')
const settingsError = ref('')
const mobileAccessDialog = ref(false)
const mobileAccessQrCode = ref('')
const mobileAccessQrCodeLoading = ref(false)
const mobileAccessCopyStatus = ref('')
const mobileAccessPromptDismissed = ref(window.localStorage.getItem(mobileAccessPromptDismissedSettingsKey) === 'true')
const generating = ref(false)
const cancelling = ref(false)
const activeJobId = ref('')
const activeImageJobRunning = ref(false)
const generationQueue = ref([])
const displayedImageGenerationJobId = ref('')
const displayedVideoGenerationJobId = ref('')
const cancellingQueueJobId = ref('')
const activityPanelOpen = ref(window.localStorage.getItem('esp-image-server.activity-panel-open') === 'true')
const activityPanelTab = ref('logs')
const diagnostics = ref([])
const diagnosticsTab = ref('summary')
const consoleOutput = ref([])
const consoleSearch = ref('')
const consoleAutoScroll = ref(true)
const consoleOutputElement = ref(null)
const generationProgress = ref(0)
const generationStage = ref('')
const steps = ref(savedGenerationSettings.steps)
const seed = ref(savedGenerationSettings.seed)
const activeModelId = ref(savedGenerationSettings.modelId)
const logoImageUrl = '/assets/test-page-logo.png'
const drawer = ref(true)
const page = ref('generate')
let statusTimer
let consoleRefreshTimer
let consoleRequestInFlight = false
let imageLibraryResizeStartX = 0
let imageLibraryResizeStartWidth = 0
let imagePreviewRequestId = 0
let videoPreviewRequestId = 0
let loadingImageGenerationJobId = ''
let loadingVideoGenerationJobId = ''
const { smAndDown: compact } = useDisplay()
const creationLibraryTemporary = computed(() => compact.value || !metadataPanePinned.value)
const mobileAccessUrl = computed(() => {
  const port = Number(serverInfo.value?.port) || 8000
  return `http://espimageserver.local:${port}`
})
const mobileAccessFallbackUrl = computed(() => serverInfo.value?.local_network_url || '')
const selectedRegisteredDisplay = computed(() => (
  displays.value.find(display => display.id === activeDisplayId.value) || null
))
const display = computed(() => {
  const selected = selectedRegisteredDisplay.value
  if (selected) return { ...selected, connected: true }
  return activeDisplayId.value ? null : legacyDisplay.value
})
const hasDisplayTargets = computed(() => Boolean(selectedRegisteredDisplay.value))
const activeDisplayOnline = computed(() => Boolean(display.value?.connected && display.value.online !== false))
const activeDisplayConnectionLabel = computed(() => {
  if (!display.value?.connected) return 'No display selected'
  return activeDisplayOnline.value ? 'Online' : 'Offline · last seen earlier'
})
const selectedTargetDisplayIds = computed(() => (
  selectedRegisteredDisplay.value ? [selectedRegisteredDisplay.value.id] : []
))
const displayTargetLabel = computed(() => {
  if (display.value?.connected) return `Active display: ${display.value.name} · ${display.value.width}×${display.value.height} · ${activeDisplayOnline.value ? 'online' : 'offline'}`
  return displays.value.length ? 'Choose active display' : 'Active display waiting'
})
const displayManagementLabel = computed(() => {
  if (display.value?.connected) return `${display.value.name} · ${display.value.width} × ${display.value.height} · ${activeDisplayConnectionLabel.value}`
  return 'No display selected'
})
const showOnDisplayLabel = computed(() => (
  display.value?.connected ? `Show on ${display.value.name}` : 'Show on display'
))
const saveToDisplaySdCardLabel = computed(() => (
  display.value?.connected ? `Save to ${display.value.name}'s SD card` : 'Save to SD card'
))
const alreadySavedToDisplaySdCardLabel = computed(() => (
  display.value?.connected ? `Already saved on ${display.value.name}'s SD card` : 'Already saved on display SD card'
))
const displaySdCardLabel = computed(() => (
  display.value?.connected ? `${display.value.name}'s SD card` : 'display SD card'
))
function buildDisplayPreviewStyle(rotation) {
  const width = Number(display.value?.width) || 4
  const height = Number(display.value?.height) || 3
  const rotated = rotation === 90 || rotation === 270
  const previewWidth = rotated ? height : width
  const previewHeight = rotated ? width : height
  return {
    '--display-preview-aspect-ratio': `${previewWidth} / ${previewHeight}`,
    '--display-preview-ratio': String(previewWidth / previewHeight)
  }
}
function buildDisplayPreviewSizeLabel(rotation) {
  if (!display.value?.connected) return 'Select a display'
  return rotation === 90 || rotation === 270
    ? `${display.value.height} × ${display.value.width}`
    : `${display.value.width} × ${display.value.height}`
}
function buildDisplayPreviewRotationLabel(rotation) {
  return rotation ? `Rotation: ${rotation}°` : 'Rotation: normal'
}
const imageDisplayPreviewStyle = computed(() => buildDisplayPreviewStyle(displayRotation.value))
const imageDisplayPreviewSizeLabel = computed(() => buildDisplayPreviewSizeLabel(displayRotation.value))
const imageDisplayPreviewRotationLabel = computed(() => buildDisplayPreviewRotationLabel(displayRotation.value))
const videoDisplayPreviewStyle = computed(() => buildDisplayPreviewStyle(videoRotation.value))
const videoDisplayPreviewSizeLabel = computed(() => buildDisplayPreviewSizeLabel(videoRotation.value))
const videoDisplayPreviewRotationLabel = computed(() => buildDisplayPreviewRotationLabel(videoRotation.value))
const compactDisplayLabel = computed(() => {
  if (!display.value?.connected) return displays.value.length ? 'Choose display' : 'Display waiting'
  return `Active: ${display.value.name}`
})
const selectedImageModelName = computed(() => models.value.find(model => model.id === activeModelId.value)?.name || 'image model')
const imageGenerationActive = computed(() => generating.value || Boolean(generationStage.value) || health.value?.image_generating === true)
const videoGenerationActive = computed(() => generatingVideo.value || health.value?.video_generating === true)
const generationBusy = computed(() => imageGenerationActive.value || videoGenerationActive.value)
const activeGenerationQueue = computed(() => generationQueue.value.filter(job => ['queued', 'running', 'cancelling'].includes(job.status)))
const finishedGenerationQueue = computed(() => generationQueue.value.filter(job => !['queued', 'running', 'cancelling'].includes(job.status)))
const runningGenerationQueueJob = computed(() => activeGenerationQueue.value.find(job => job.status === 'running' || job.status === 'cancelling') || null)
const activeImageQueueJob = computed(() => activeGenerationQueue.value.find(job => job.kind === 'image' && job.status !== 'queued') || activeGenerationQueue.value.find(job => job.kind === 'image') || null)
const activeVideoQueueJob = computed(() => activeGenerationQueue.value.find(job => job.kind === 'video' && job.status !== 'queued') || activeGenerationQueue.value.find(job => job.kind === 'video') || null)
const filteredConsoleOutput = computed(() => {
  const query = consoleSearch.value.trim().toLocaleLowerCase()
  return query ? consoleOutput.value.filter(line => line.toLocaleLowerCase().includes(query)) : consoleOutput.value
})
const appBarStatus = computed(() => {
  const runningJob = runningGenerationQueueJob.value
  if (runningJob) {
    const isVideo = runningJob.kind === 'video'
    const progress = isVideo && activeVideoJobId.value === runningJob.id
      ? videoProgress.value
      : !isVideo && activeJobId.value === runningJob.id
        ? generationProgress.value
        : runningJob.progress
    const kind = isVideo ? 'video' : 'image'
    const cancelling = runningJob.status === 'cancelling'
    return {
      color: 'primary', icon: isVideo ? 'mdi-movie-open-outline' : 'mdi-image-outline', page: isVideo ? 'video' : 'generate',
      label: cancelling ? `Cancelling ${kind}` : Number.isFinite(progress) && progress > 0 ? `Generating ${kind} · ${progress}%` : `Preparing ${kind}`,
      compactLabel: cancelling ? 'Cancel' : Number.isFinite(progress) && progress > 0 ? `${progress}%` : isVideo ? 'Video' : 'Image'
    }
  }
  if (videoGenerationActive.value) {
    const job = health.value?.active_video_job
    const progress = generatingVideo.value ? videoProgress.value : job?.progress
    const cancelling = cancelVideoOnStart.value || cancellingVideo.value || job?.status === 'cancelling'
    return {
      color: 'primary', icon: 'mdi-movie-open-outline', page: 'video',
      label: cancelling ? 'Cancelling video' : Number.isFinite(progress) && progress > 0 ? `Generating video · ${progress}%` : 'Preparing video',
      compactLabel: cancelling ? 'Cancel' : Number.isFinite(progress) && progress > 0 ? `${progress}%` : 'Video'
    }
  }
  if (imageGenerationActive.value) {
    const job = health.value?.active_image_job
    const progress = generating.value ? generationProgress.value : job?.progress
    const cancelling = cancelling.value || job?.status === 'cancelling'
    const downloadingModel = generationStage.value.startsWith('Downloading')
    const loadingModel = generationStage.value.startsWith('Loading')
    const activity = downloadingModel
      ? `Downloading ${selectedImageModelName.value}`
      : loadingModel
        ? `Loading ${selectedImageModelName.value}`
        : 'Generating image'
    return {
      color: 'primary', icon: 'mdi-image-outline', page: 'generate',
      label: cancelling ? 'Cancelling image' : Number.isFinite(progress) && progress > 0 ? `${activity} · ${progress}%` : generationStage.value || 'Preparing image',
      compactLabel: cancelling ? 'Cancel' : Number.isFinite(progress) && progress > 0 ? `${progress}%` : downloadingModel ? 'Download' : 'Image'
    }
  }
  if (health.value?.status === 'ready') {
    return { color: 'success', icon: 'mdi-server', page: '', label: 'Server ready', compactLabel: 'Ready' }
  }
  return { color: 'warning', icon: 'mdi-server', page: '', label: 'Server loading', compactLabel: 'Loading' }
})
const modelOptions = computed(() => models.value.map(model => ({
  title: `${model.name} — ${model.speed} (${model.hardware})`,
  value: model.id
})))
const videoDurationSeconds = computed(() => {
  const frames = Number(videoFrames.value)
  const fps = Number(videoFps.value)
  return Number.isFinite(frames) && frames > 0 && Number.isFinite(fps) && fps > 0 ? frames / fps : 0
})
const videoDurationLabel = computed(() => `${videoDurationSeconds.value.toFixed(1)} seconds`)
const videoDurationPresets = [
  { title: '1 sec', seconds: 1 },
  { title: '2 sec', seconds: 2 },
  { title: '3 sec', seconds: 3 },
  { title: '5 sec', seconds: 5 },
  { title: '8 sec', seconds: 8 },
  { title: '10 sec', seconds: 10 },
  { title: '15 sec', seconds: 15 },
  { title: '20 sec', seconds: 20 }
]

function isVideoDurationAvailable(seconds, fps = Number(videoFps.value)) {
  return Number.isFinite(fps) && fps > 0 && Number(seconds) * fps <= 249
}

function validVideoFramesForDuration(seconds, fps = Number(videoFps.value)) {
  const targetFrames = Number(seconds) * fps
  const block = Math.min(31, Math.max(1, Math.round((targetFrames - 1) / 8)))
  return block * 8 + 1
}

function selectVideoDuration(seconds) {
  videoDurationPresetSeconds.value = seconds
  videoFrames.value = validVideoFramesForDuration(seconds)
}

function matchingVideoDurationPreset() {
  return videoDurationPresets.find(preset => isVideoDurationAvailable(preset.seconds) && Number(videoFrames.value) === validVideoFramesForDuration(preset.seconds))?.seconds ?? null
}

videoDurationPresetSeconds.value = matchingVideoDurationPreset()
const videoModels = [
  { title: 'LTX-Video 2B distilled — fast', value: 'ltx-2b-0.9.6-distilled', description: 'Best for quick short animations. Uses less graphics-card memory.' },
  { title: 'LTX-Video 2B quality — detailed', value: 'ltx-2b-0.9.6-dev', description: 'Best when detail matters more than speed. Much slower and needs more graphics-card memory.' },
  { title: 'Wan 2.1 T2V 1.3B — text-to-video', value: 'wan-2.1-t2v-1.3b', description: 'A detailed text-to-video alternative. Slower and uses system memory to work with 8 GB graphics cards.' },
  { title: 'HunyuanVideo 1.5 480p — quality', value: 'hunyuanvideo-1.5-480p', description: 'High-quality text-to-video and image animation. Slower and best on a capable NVIDIA graphics card.' }
]
const selectedVideoModel = computed(() => videoModels.find(model => model.value === videoModelId.value) || videoModels[0])
const videoStepOptions = computed(() => {
  if (videoModelId.value === 'ltx-2b-0.9.6-dev') return [10, 15, 20, 25, 30, 35, 40]
  if (videoModelId.value === 'wan-2.1-t2v-1.3b' || videoModelId.value === 'hunyuanvideo-1.5-480p') return [20, 25, 30, 35, 40, 45, 50]
  return [4, 5, 6, 7, 8]
})
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
function creationModelName(creation) {
  return creation.metadata?.model?.name || 'Other creations'
}

function creationDisplayName(creation) {
  return creation.metadata?.display?.name || ''
}

const creationSdCardInventoryConfirmed = computed(() => Number(displaySdCard.value?.report_version) > 0)
const creationSdCardFilterOptions = [
  { title: 'On display SD card', value: 'on_sd_card' },
  { title: 'Not on display SD card', value: 'not_on_sd_card' }
]

function displaySdCardFiles() {
  return Array.isArray(displaySdCard.value?.files) ? displaySdCard.value.files : []
}

const selectedSdCardFiles = computed(() => {
  const selectedNames = new Set(selectedSdCardFileNames.value)
  return displaySdCardFiles().filter(file => selectedNames.has(file.name))
})

function setSdCardFileSelected(filename, selected) {
  const selectedNames = new Set(selectedSdCardFileNames.value)
  if (selected) selectedNames.add(filename)
  else selectedNames.delete(filename)
  selectedSdCardFileNames.value = [...selectedNames]
}

function savedVideoFps(savedVideo) {
  const fps = Number(savedVideo.metadata?.fps)
  return Number.isFinite(fps) ? Math.max(1, Math.min(24, Math.round(fps))) : 15
}

function creationSdCardStatus(creation, mediaType) {
  if (!creation) return { known: false, present: false, file: null, activeFormat: false }
  if (!creationSdCardInventoryConfirmed.value) return { known: false, present: false, file: null, activeFormat: false }
  if (!displaySdCard.value?.available) return { known: true, present: false, file: null, activeFormat: false }
  const files = displaySdCardFiles().filter(file => (file.type || (String(file.name || '').endsWith('.mjpeg') ? 'video' : 'image')) === mediaType)
  if (mediaType === 'image') {
    const contentKey = String(creation.sd_card_content_key || '')
    const imageHash = contentKey.startsWith('v1-') ? contentKey.slice(3) : ''
    const file = files.find(item => {
      const name = String(item.name || '')
      return (contentKey && (String(item.content_key || '') === contentKey || name.endsWith(`-${contentKey}.jpg`)))
        || (imageHash && name.endsWith(`-${imageHash}.jpg`))
    }) || null
    return { known: true, present: Boolean(file), file, activeFormat: Boolean(file) }
  }
  const videoId = String(creation.id || '')
  const expectedKey = display.value?.connected
    ? `v1-${videoId}-${display.value.width}x${display.value.height}-fps${savedVideoFps(creation)}`
    : ''
  const file = files.find(item => {
    const name = String(item.name || '')
    const contentKey = String(item.content_key || '')
    return contentKey.startsWith(`v1-${videoId}-`)
      || name.includes(`-v1-${videoId}-`)
      || name.endsWith(`-${videoId.slice(0, 8)}-fps${savedVideoFps(creation)}.mjpeg`)
  }) || null
  const filename = String(file?.name || '')
  const activeFormat = Boolean(file) && (
    (Boolean(expectedKey) && (String(file.content_key || '') === expectedKey || filename.endsWith(`-${expectedKey}.mjpeg`)))
    || filename.endsWith(`-${videoId.slice(0, 8)}-fps${savedVideoFps(creation)}.mjpeg`)
  )
  return { known: true, present: Boolean(file), file, activeFormat }
}

function creationSdCardLabel(creation, mediaType) {
  const sdCardStatus = creationSdCardStatus(creation, mediaType)
  if (!sdCardStatus.present) return ''
  if (mediaType === 'video' && display.value?.connected && !sdCardStatus.activeFormat) return 'On SD card · another format'
  if (mediaType === 'video' && !display.value?.connected) return 'On display SD card'
  if (mediaType === 'video') return `On SD card · ${display?.value?.width}×${display?.value?.height} · ${savedVideoFps(creation)} fps`
  return 'On display SD card'
}

function creationIsOnDisplaySdCard(creation, mediaType) {
  return creationSdCardStatus(creation, mediaType).present
}

function creationIsSavedForCurrentDisplay(creation, mediaType) {
  return creationSdCardStatus(creation, mediaType).activeFormat
}

function matchesCreationFilters(creation, mediaType) {
  if (creationModelFilter.value && creationModelName(creation) !== creationModelFilter.value) return false
  if (creationDisplayFilter.value === '__no_display__' && creationDisplayName(creation)) return false
  if (creationDisplayFilter.value && creationDisplayFilter.value !== '__no_display__' && creationDisplayName(creation) !== creationDisplayFilter.value) return false
  if (creationSdCardFilter.value === 'on_sd_card') return creationIsOnDisplaySdCard(creation, mediaType)
  if (creationSdCardFilter.value === 'not_on_sd_card') return !creationIsOnDisplaySdCard(creation, mediaType)
  return true
}

const creationModelOptions = computed(() => [...new Set(
  [...savedImages.value, ...savedVideos.value].map(creationModelName)
)].sort().map(name => ({ title: name, value: name })))
const creationDisplayOptions = computed(() => {
  const creations = [...savedImages.value, ...savedVideos.value]
  const names = [...new Set(creations.map(creationDisplayName).filter(Boolean))].sort()
  const options = names.map(name => ({ title: name, value: name }))
  if (creations.some(creation => !creationDisplayName(creation))) {
    options.push({ title: 'No display recorded', value: '__no_display__' })
  }
  return options
})
const filteredSavedImages = computed(() => savedImages.value.filter(image => matchesCreationFilters(image, 'image')))
const filteredSavedVideos = computed(() => savedVideos.value.filter(video => matchesCreationFilters(video, 'video')))
const filteredCreationsCount = computed(() => filteredSavedImages.value.length + filteredSavedVideos.value.length)
const savedImageGroups = computed(() => {
  const groups = new Map()
  for (const savedImage of filteredSavedImages.value) {
    const modelName = savedImage.metadata?.model?.name || 'Other images'
    if (!groups.has(modelName)) groups.set(modelName, [])
    groups.get(modelName).push(savedImage)
  }
  return [...groups].map(([modelName, images]) => ({ modelName, images }))
})
const savedVideoGroups = computed(() => {
  const groups = new Map()
  for (const savedVideo of filteredSavedVideos.value) {
    const modelName = savedVideo.metadata?.model?.name || 'Other videos'
    if (!groups.has(modelName)) groups.set(modelName, [])
    groups.get(modelName).push(savedVideo)
  }
  return [...groups].map(([modelName, videos]) => ({ modelName, videos }))
})

watch([prompt, negativePrompt, steps, seed, activeModelId], () => {
  window.localStorage.setItem(generationSettingsKey, JSON.stringify({
    prompt: prompt.value,
    negativePrompt: negativePrompt.value,
    steps: Number(steps.value),
    seed: seed.value === '' ? null : Number(seed.value),
    modelId: activeModelId.value
  }))
})

watch([videoPrompt, videoFrames, videoFps, videoSteps, videoModelId, videoSeed], () => {
  window.localStorage.setItem(videoGenerationSettingsKey, JSON.stringify({
    prompt: videoPrompt.value,
    frames: Number(videoFrames.value),
    fps: Number(videoFps.value),
    steps: Number(videoSteps.value),
    modelId: videoModelId.value,
    seed: videoSeed.value === '' ? null : Number(videoSeed.value)
}))
})

watch(videoModelId, modelId => {
  videoSteps.value = modelId === 'ltx-2b-0.9.6-dev' || modelId === 'wan-2.1-t2v-1.3b' || modelId === 'hunyuanvideo-1.5-480p' ? 30 : 8
  if (modelId === 'wan-2.1-t2v-1.3b') videoSourceImage.value = null
})

watch(videoFps, fps => {
  if (videoDurationPresetSeconds.value !== null) {
    if (isVideoDurationAvailable(videoDurationPresetSeconds.value, Number(fps))) {
      videoFrames.value = validVideoFramesForDuration(videoDurationPresetSeconds.value, Number(fps))
    } else {
      videoDurationPresetSeconds.value = null
    }
  }
})

watch(videoFrames, frames => {
  if (videoDurationPresetSeconds.value === null) return
  if (Number(frames) !== validVideoFramesForDuration(videoDurationPresetSeconds.value)) {
    videoDurationPresetSeconds.value = null
  }
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

watch(sdCardItemsPerPage, itemsPerPage => {
  window.localStorage.setItem(sdCardItemsPerPageSettingsKey, String(itemsPerPage))
})

watch(activeDisplayOnline, online => {
  if (!online) selectedSdCardFileNames.value = []
})

watch(compact, async isCompact => {
  if (isCompact) {
    drawer.value = false
    metadataPanePinned.value = false
    // The drawer changes from permanent to temporary with this breakpoint.
    // Let that prop change settle before closing it; otherwise the old
    // permanent drawer can emit its open state back into v-model.
    await nextTick()
    metadataPane.value = false
  }
}, { immediate: true })

watch(activityPanelOpen, isOpen => {
  window.localStorage.setItem('esp-image-server.activity-panel-open', String(isOpen))
})

watch(diagnosticsTab, tab => {
  if (tab === 'console' && consoleAutoScroll.value) nextTick(scrollConsoleToBottom)
  updateConsoleRefresh()
})

watch(page, (nextPage, previousPage) => {
  if (previousPage === 'display-experience' && nextPage !== 'display-experience') void stopDisplayExperiencePreview()
  updateConsoleRefresh()
})

watch(activeDisplayId, displayId => {
  if (displayId) window.localStorage.setItem(activeDisplaySettingsKey, displayId)
  else window.localStorage.removeItem(activeDisplaySettingsKey)
  displayExperiencePreviewing.value = false
  selectedSdCardFileNames.value = []
  if (!display.value?.connected) {
    displayRotation.value = 0
    videoRotation.value = 0
    displaySdCard.value = { available: false, files: [] }
    return
  }
  void loadDisplaySettings()
  void loadDisplaySdCard()
  if (page.value === 'display-experience') void loadDisplayExperience()
})

const displayMessage = computed(() => {
  if (!display.value?.connected) {
    return displays.value.length
      ? 'Choose an active display to manage its settings and receive generated images.'
      : 'Waiting for the ESP32 board to report its integrated display...'
  }
  if (!activeDisplayOnline.value) {
    return `${display.value.name} is offline (last seen earlier). Generated images remain ready for it, while display and SD-card commands are unavailable.`
  }
  const firmwareVersion = display.value.firmware_version
  const availability = display.value.online === false ? 'Last seen earlier' : 'Online'
  return `${display.value.name} — ${availability}, ${display.value.width} × ${display.value.height}. Firmware ${firmwareVersion}. Images will fit this screen.`
})

function selectedDisplayEndpoint(suffix) {
  const selected = selectedRegisteredDisplay.value
  return selected ? `/displays/${encodeURIComponent(selected.id)}${suffix}` : suffix
}

function selectedDisplayCommandEndpoint(commandId) {
  return `${selectedDisplayEndpoint('/display-commands')}/${encodeURIComponent(commandId)}`
}

function activeDisplayCommandUnavailableMessage() {
  if (!display.value?.connected) return 'Choose one display before managing it.'
  return `${display.value.name} is offline. Reconnect it before sending display or SD-card commands.`
}

function displaySdCardThumbnailUrl(filename) {
  return selectedDisplayEndpoint(`/display-sd-card/thumbnails/${encodeURIComponent(filename)}`)
}

function selectActiveDisplay(displayId) {
  activeDisplayId.value = displayId
  displayPickerOpen.value = false
  const selected = displays.value.find(target => target.id === displayId)
  if (selected) {
    displayConnectedMessage.value = `Working with ${selected.name}. New display and SD-card actions apply to this display.`
    displayConnectedSnackbar.value = true
  }
}

async function loadDisplay() {
  try {
    const previousKey = display.value?.connected && display.value.online !== false
      ? `${display.value.id || 'legacy'}:${display.value.name}:${display.value.width}x${display.value.height}:${display.value.firmware_version}`
      : ''
    const [registeredResponse, legacyResponse] = await Promise.all([
      fetch('/displays', { cache: 'no-store' }),
      fetch('/display', { cache: 'no-store' })
    ])
    const registered = registeredResponse.ok ? await registeredResponse.json() : []
    const nextDisplays = Array.isArray(registered) ? registered : []
    displays.value = nextDisplays
    legacyDisplay.value = !nextDisplays.length && legacyResponse.ok ? await legacyResponse.json() : null
    const availableIds = new Set(nextDisplays.map(display => display.id))
    if (activeDisplayId.value && !availableIds.has(activeDisplayId.value)) activeDisplayId.value = ''
    if (nextDisplays.length && !activeDisplayId.value) activeDisplayId.value = nextDisplays[0].id
    const nextDisplay = display.value
    const nextKey = nextDisplay?.connected && nextDisplay.online !== false
      ? `${nextDisplay.id || 'legacy'}:${nextDisplay.name}:${nextDisplay.width}x${nextDisplay.height}:${nextDisplay.firmware_version}`
      : ''
    if (nextKey && nextKey !== previousKey) {
      const firmwareVersion = nextDisplay.firmware_version
      displayConnectedMessage.value = `${nextDisplay.name} connected (${nextDisplay.width} × ${nextDisplay.height}, firmware ${firmwareVersion}).`
      displayConnectedSnackbar.value = true
    }
  } catch {
    displays.value = []
    legacyDisplay.value = null
    activeDisplayId.value = ''
  }
}

async function loadDisplaySettings() {
  if (!display.value?.connected) {
    displayRotation.value = 0
    videoRotation.value = 0
    return
  }
  try {
    const [imageSettings, videoSettings] = await Promise.all([
      fetch(selectedDisplayEndpoint('/display-settings')).then(response => response.json()),
      fetch(selectedDisplayEndpoint('/video-display-settings')).then(response => response.json())
    ])
    displayRotation.value = imageSettings.rotation
    videoRotation.value = videoSettings.rotation
  } catch {
    displayRotation.value = 0
    videoRotation.value = 0
  }
}

async function setDisplayRotation(rotation) {
  if (!display.value?.connected) return
  const previousRotation = displayRotation.value
  displayRotation.value = rotation
  error.value = ''
  try {
    const response = await fetch(selectedDisplayEndpoint('/display-settings'), {
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
    if (selectedRegisteredDisplay.value) {
      displays.value = displays.value.map(display => (
        display.id === selectedRegisteredDisplay.value.id ? { ...display, rotation: settings.rotation } : display
      ))
    }
    status.value = `Image rotation saved for ${display.value.name}. It will be used for the next image.`
  } catch (requestError) {
    displayRotation.value = previousRotation
    error.value = `Could not save image rotation: ${requestError.message}`
  }
}

async function setVideoRotation(rotation) {
  if (!display.value?.connected) return
  const previousRotation = videoRotation.value
  videoRotation.value = rotation
  error.value = ''
  try {
    const response = await fetch(selectedDisplayEndpoint('/video-display-settings'), {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ rotation })
    })
    if (!response.ok) {
      const body = await response.json().catch(() => ({}))
      throw new Error(body.detail || `Request failed (${response.status})`)
    }
    const settings = await response.json()
    videoRotation.value = settings.rotation
    if (selectedRegisteredDisplay.value) {
      displays.value = displays.value.map(display => (
        display.id === selectedRegisteredDisplay.value.id ? { ...display, video_rotation: settings.rotation } : display
      ))
    }
    status.value = `Video rotation saved for ${display.value.name}. It will be used for the next video.`
  } catch (requestError) {
    videoRotation.value = previousRotation
    error.value = `Could not save video rotation: ${requestError.message}`
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

async function loadVideoModels() {
  try {
    const response = await fetch('/video-models')
    availableVideoModels.value = response.ok ? await response.json() : []
  } catch {
    availableVideoModels.value = []
  }
}

function confirmRemoveImageModel(model) {
  imageModelToRemove.value = model
  removeImageModelDialog.value = true
}

async function removeImageModel() {
  const model = imageModelToRemove.value
  if (!model || removingImageModelId.value) return
  removingImageModelId.value = model.id
  try {
    const response = await fetch(`/models/${encodeURIComponent(model.id)}`, { method: 'DELETE' })
    if (!response.ok) {
      const body = await response.json().catch(() => ({}))
      throw new Error(body.detail || `Request failed (${response.status})`)
    }
    removeImageModelDialog.value = false
    status.value = `${model.name} was removed to free disk space.`
    await loadModels()
  } catch (requestError) {
    error.value = `Could not remove ${model.name}: ${requestError.message}`
  } finally {
    removingImageModelId.value = ''
  }
}

function confirmRemoveVideoModel(model) {
  videoModelToRemove.value = model
  removeVideoModelDialog.value = true
}

async function removeVideoModel() {
  const model = videoModelToRemove.value
  if (!model || removingVideoModelId.value) return
  removingVideoModelId.value = model.id
  try {
    const response = await fetch(`/video-models/${encodeURIComponent(model.id)}`, { method: 'DELETE' })
    if (!response.ok) {
      const body = await response.json().catch(() => ({}))
      throw new Error(body.detail || `Request failed (${response.status})`)
    }
    removeVideoModelDialog.value = false
    videoStage.value = `${model.name} was removed to free disk space.`
    await loadVideoModels()
  } catch (requestError) {
    videoError.value = `Could not remove ${model.name}: ${requestError.message}`
  } finally {
    removingVideoModelId.value = ''
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

async function loadGenerationQueue() {
  try {
    const response = await fetch('/generation-queue', { cache: 'no-store' })
    const jobs = response.ok ? await response.json() : []
    generationQueue.value = jobs
    void loadLatestCompletedGenerationResults(jobs)
  } catch {
    generationQueue.value = []
  }
}

function latestCompletedGenerationJob(jobs, kind) {
  return jobs.find(job => job.kind === kind && job.status === 'complete') || null
}

function resultPanelQueueStatus(job) {
  if (!job) return ''
  if (job.status === 'queued') return job.queue_position ? `Queued · position ${job.queue_position}` : 'Queued'
  if (job.status === 'cancelling') return 'Cancelling'
  return Number.isFinite(job.progress) && job.progress > 0 ? `Generating · ${job.progress}%` : 'Starting'
}

async function updateImagePreview(imageBlob, {
  requestId = ++imagePreviewRequestId,
  jobId = '',
  metadata = null,
  savedToLibrary = false,
  savedImage = null
} = {}) {
  const nextImageUrl = URL.createObjectURL(imageBlob)
  let nextPreviewUrl
  try {
    nextPreviewUrl = await createDisplayPreview(imageBlob)
  } catch (requestError) {
    URL.revokeObjectURL(nextImageUrl)
    throw requestError
  }
  if (requestId !== imagePreviewRequestId) {
    URL.revokeObjectURL(nextImageUrl)
    URL.revokeObjectURL(nextPreviewUrl)
    return false
  }
  if (imageUrl.value) URL.revokeObjectURL(imageUrl.value)
  if (previewUrl.value) URL.revokeObjectURL(previewUrl.value)
  imageUrl.value = nextImageUrl
  previewUrl.value = nextPreviewUrl
  previewFittedFor.value = display.value?.connected ? display.value : null
  generatedMetadata.value = metadata
  selectedSavedImage.value = savedImage
  currentImageSavedToLibrary.value = savedToLibrary
  if (jobId) displayedImageGenerationJobId.value = jobId
  return true
}

async function updateVideoPreview(videoBlob, {
  requestId = ++videoPreviewRequestId,
  jobId = '',
  savedToLibrary = false
} = {}) {
  const nextVideoUrl = URL.createObjectURL(videoBlob)
  if (requestId !== videoPreviewRequestId) {
    URL.revokeObjectURL(nextVideoUrl)
    return false
  }
  if (videoUrl.value) URL.revokeObjectURL(videoUrl.value)
  videoUrl.value = nextVideoUrl
  completedVideoJobId.value = jobId
  videoSavedToCreationLibrary.value = savedToLibrary
  if (jobId) displayedVideoGenerationJobId.value = jobId
  return true
}

async function loadCompletedImageGeneration(job, { force = false } = {}) {
  if (!force && (displayedImageGenerationJobId.value === job.id || loadingImageGenerationJobId === job.id)) return
  const requestId = ++imagePreviewRequestId
  loadingImageGenerationJobId = job.id
  try {
    const response = await fetch(`/generation-jobs/${encodeURIComponent(job.id)}/image`)
    if (!response.ok) throw new Error(`Request failed (${response.status})`)
    await updateImagePreview(await response.blob(), {
      requestId,
      jobId: job.id,
      savedToLibrary: autoSaveImages.value
    })
  } catch {
    // A completed job can be cleared between the queue refresh and this request.
    // Keep the last result on screen instead of replacing it with an error state.
  } finally {
    if (loadingImageGenerationJobId === job.id) loadingImageGenerationJobId = ''
  }
}

async function loadCompletedVideoGeneration(job, { force = false } = {}) {
  if (!force && (displayedVideoGenerationJobId.value === job.id || loadingVideoGenerationJobId === job.id)) return
  const requestId = ++videoPreviewRequestId
  loadingVideoGenerationJobId = job.id
  try {
    const response = await fetch(`/video-generation-jobs/${encodeURIComponent(job.id)}/video`)
    if (!response.ok) throw new Error(`Request failed (${response.status})`)
    await updateVideoPreview(await response.blob(), { requestId, jobId: job.id })
  } catch {
    // Keep the previous completed video if a queue entry disappears before it loads.
  } finally {
    if (loadingVideoGenerationJobId === job.id) loadingVideoGenerationJobId = ''
  }
}

async function loadLatestCompletedGenerationResults(jobs) {
  const latestImage = latestCompletedGenerationJob(jobs, 'image')
  const latestVideo = latestCompletedGenerationJob(jobs, 'video')
  await Promise.all([
    latestImage ? loadCompletedImageGeneration(latestImage) : Promise.resolve(),
    latestVideo ? loadCompletedVideoGeneration(latestVideo) : Promise.resolve()
  ])
}

async function loadDiagnostics() {
  try {
    const response = await fetch('/diagnostics', { cache: 'no-store' })
    diagnostics.value = response.ok ? await response.json() : []
  } catch {
    diagnostics.value = []
  }
}

async function loadConsoleOutput() {
  if (consoleRequestInFlight) return
  consoleRequestInFlight = true
  try {
    const response = await fetch('/console-output', { cache: 'no-store' })
    consoleOutput.value = response.ok ? await response.json() : []
    await nextTick()
    if (diagnosticsTab.value === 'console' && consoleAutoScroll.value) scrollConsoleToBottom()
  } catch {
    consoleOutput.value = []
  } finally {
    consoleRequestInFlight = false
  }
}

function updateConsoleRefresh() {
  window.clearInterval(consoleRefreshTimer)
  consoleRefreshTimer = undefined
  if (page.value !== 'diagnostics' || diagnosticsTab.value !== 'console') return
  void loadConsoleOutput()
  consoleRefreshTimer = window.setInterval(loadConsoleOutput, 1000)
}

async function clearDiagnostics() {
  await fetch('/diagnostics', { method: 'DELETE' })
  diagnostics.value = []
}

async function copyDiagnostics() {
  const text = diagnostics.value.map(entry => `${entry.timestamp} [${entry.level.toUpperCase()}] ${entry.source}: ${entry.message}`).join('\n')
  await navigator.clipboard?.writeText(text)
}

function dismissMobileAccessPrompt() {
  mobileAccessPromptDismissed.value = true
  window.localStorage.setItem(mobileAccessPromptDismissedSettingsKey, 'true')
}

async function copyText(text) {
  if (navigator.clipboard?.writeText) {
    await navigator.clipboard.writeText(text)
    return
  }
  const input = document.createElement('textarea')
  input.value = text
  input.setAttribute('readonly', '')
  input.style.position = 'fixed'
  input.style.opacity = '0'
  document.body.appendChild(input)
  input.select()
  const copied = document.execCommand('copy')
  input.remove()
  if (!copied) throw new Error('Copy is not available in this browser')
}

async function copyMobileAccessUrl(url, label) {
  mobileAccessCopyStatus.value = ''
  try {
    await copyText(url)
    mobileAccessCopyStatus.value = `${label} address copied.`
  } catch (copyError) {
    mobileAccessCopyStatus.value = `Could not copy the address: ${copyError.message}`
  }
}

async function openMobileAccessDialog(dismissPrompt = false) {
  if (dismissPrompt) dismissMobileAccessPrompt()
  mobileAccessDialog.value = true
  mobileAccessCopyStatus.value = ''
  mobileAccessQrCodeLoading.value = true
  try {
    mobileAccessQrCode.value = await QRCode.toDataURL(mobileAccessUrl.value, {
      width: 256,
      margin: 1,
      errorCorrectionLevel: 'M'
    })
  } catch (qrError) {
    mobileAccessQrCode.value = ''
    mobileAccessCopyStatus.value = `Could not create the QR code: ${qrError.message}`
  } finally {
    mobileAccessQrCodeLoading.value = false
  }
}

function updateConsoleAutoScroll(event) {
  const element = event.currentTarget
  consoleAutoScroll.value = element.scrollHeight - element.scrollTop - element.clientHeight < 16
}

function scrollConsoleToBottom() {
  consoleAutoScroll.value = true
  const element = consoleOutputElement.value
  if (element) element.scrollTop = element.scrollHeight
}

async function clearConsoleOutput() {
  await fetch('/console-output', { method: 'DELETE' })
  consoleOutput.value = []
}

async function copyConsoleOutput() {
  await navigator.clipboard?.writeText(filteredConsoleOutput.value.join('\n'))
}

async function cancelQueuedGeneration(job) {
  if (!job?.cancellable || cancellingQueueJobId.value) return
  cancellingQueueJobId.value = job.id
  try {
    const response = await fetch(`/generation-queue/${encodeURIComponent(job.id)}`, { method: 'DELETE' })
    if (!response.ok) throw new Error(`Request failed (${response.status})`)
    await loadGenerationQueue()
  } finally {
    cancellingQueueJobId.value = ''
  }
}

async function clearFinishedGenerationQueue() {
  const response = await fetch('/generation-queue', { method: 'DELETE' })
  if (!response.ok) throw new Error(`Request failed (${response.status})`)
  await loadGenerationQueue()
}

async function openQueuedGeneration(job) {
  if (job.status !== 'complete') return
  if (job.kind === 'image') {
    await loadCompletedImageGeneration(job, { force: true })
    page.value = 'generate'
    return
  }
  await loadCompletedVideoGeneration(job, { force: true })
  page.value = 'video'
}

function selectModelById(modelId) {
  const model = models.value.find(candidate => candidate.id === modelId)
  if (!model) return
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

function formatGenerationTime(seconds) {
  const duration = Number(seconds)
  if (!Number.isFinite(duration) || duration < 0) return ''
  if (duration < 60) return `${duration < 10 ? duration.toFixed(1) : Math.round(duration)} sec`
  const minutes = Math.floor(duration / 60)
  const remainingSeconds = Math.round(duration % 60)
  return `${minutes}m ${remainingSeconds}s`
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

async function loadSavedVideos() {
  try {
    const response = await fetch('/saved-videos')
    savedVideos.value = response.ok ? await response.json() : []
  } catch {
    savedVideos.value = []
  }
}

function showSavedVideoActions(savedVideo, position) {
  contextMenuSavedVideo.value = savedVideo
  savedVideoContextMenuPosition.value = position
  savedVideoContextMenu.value = false
  window.requestAnimationFrame(() => { savedVideoContextMenu.value = true })
}

function openSavedVideoContextMenu(event, savedVideo) {
  event.preventDefault()
  showSavedVideoActions(savedVideo, [event.clientX, event.clientY])
}

function openSavedVideoActions(event, savedVideo) {
  const bounds = event.currentTarget.getBoundingClientRect()
  showSavedVideoActions(savedVideo, [bounds.right, bounds.bottom])
}

async function openSavedVideo(savedVideo) {
  await useSavedVideoSettings(savedVideo.metadata, 'all')
  videoError.value = ''
  videoStage.value = 'Loading saved video...'
  const requestId = ++videoPreviewRequestId
  try {
    const response = await fetch(`/saved-videos/${encodeURIComponent(savedVideo.id)}/video`)
    if (!response.ok) throw new Error(`Request failed (${response.status})`)
    const shown = await updateVideoPreview(await response.blob(), { requestId, savedToLibrary: true })
    if (!shown) return
    completedVideoSavedId.value = savedVideo.id
    videoStage.value = 'Viewing saved video from the Creation Gallery.'
  } catch (requestError) {
    videoError.value = `Could not open this saved video: ${requestError.message}`
    videoStage.value = ''
  }
}

async function useSavedVideoSettings(metadata, setting) {
  if (!metadata) return
  savedVideoContextMenu.value = false
  if (setting === 'prompt' || setting === 'all') videoPrompt.value = metadata.prompt || videoPrompt.value
  if (setting === 'frames' || setting === 'fps' || setting === 'all') videoDurationPresetSeconds.value = null
  if (setting === 'frames' || setting === 'all') videoFrames.value = metadata.frames || videoFrames.value
  if (setting === 'fps' || setting === 'all') videoFps.value = metadata.fps || videoFps.value
  if (setting === 'model' || setting === 'all') {
    if (metadata.model?.id) {
      videoModelId.value = metadata.model.id
      await nextTick()
    }
  }
  if (setting === 'steps' || setting === 'all') videoSteps.value = metadata.steps || videoSteps.value
  if (setting === 'seed' || setting === 'all') videoSeed.value = metadata.seed ?? createRandomSeed()
  if (setting === 'all') videoSourceImage.value = savedImages.value.find(image => image.id === metadata.source_image_id) || null
  page.value = 'video'
  videoStage.value = setting === 'all' ? 'Saved video settings restored.' : `Saved video ${setting} restored.`
  if (!metadataPanePinned.value) metadataPane.value = false
}

async function saveSavedVideoToDisplaySdCard() {
  const savedVideo = contextMenuSavedVideo.value
  if (!savedVideo || savingVideoToDisplaySdCard.value) return
  savedVideoContextMenu.value = false
  await saveVideoToDisplaySdCard(savedVideo.id)
}

async function saveVideoToDisplaySdCard(videoId) {
  if (!videoId || !activeDisplayOnline.value || savingVideoToDisplaySdCard.value) return null
  savingVideoToDisplaySdCard.value = true
  error.value = ''
  status.value = ''
  try {
    status.value = 'Checking the display SD card for this video...'
    await refreshDisplaySdCardInventory()
    const response = await fetch(
      `${selectedDisplayEndpoint('/display-commands/save-saved-video')}/${encodeURIComponent(videoId)}`,
      { method: 'POST' }
    )
    if (!response.ok) {
      const body = await response.json().catch(() => ({}))
      throw new Error(body.detail || `Request failed (${response.status})`)
    }
    const command = await response.json()
    if (command.status === 'already_saved') {
      status.value = command.detail || 'This video is already on the display SD card.'
      return { filename: String(command.filename || ''), ready: true, reused: true }
    }
    status.value = 'Copying video to the display SD card for offline playback. It will be converted to MJPEG first.'
    for (let attempt = 0; attempt < 90; attempt += 1) {
      await new Promise(resolve => window.setTimeout(resolve, 1000))
      const commandResponse = await fetch(selectedDisplayCommandEndpoint(command.id))
      if (!commandResponse.ok) continue
      const result = await commandResponse.json()
      if (result.status === 'complete') {
        status.value = 'Video saved to the display SD card for offline playback.'
        return { filename: String(command.filename || ''), ready: true }
      }
      if (result.status === 'failed') throw new Error(result.detail || 'The display could not play this video')
    }
    status.value = 'The display is still preparing the video for offline playback.'
    return { filename: String(command.filename || ''), ready: false }
  } catch (requestError) {
    error.value = `Could not save the video to the display SD card: ${requestError.message}`
    return null
  } finally {
    savingVideoToDisplaySdCard.value = false
  }
}

async function showSavedVideoOnDisplay(videoId = completedVideoSavedId.value) {
  if (!activeDisplayOnline.value || showingVideoOnDisplay.value) return
  showingVideoOnDisplay.value = true
  videoError.value = ''
  try {
    let savedVideoId = videoId
    if (!savedVideoId) {
      videoStage.value = 'Saving video to your Creation Gallery before showing it on the display...'
      savedVideoId = await saveVideoToCreationLibrary()
      if (!savedVideoId) return
    }
    videoStage.value = 'Copying video to the display SD card before playback...'
    const saved = await saveVideoToDisplaySdCard(savedVideoId)
    if (!saved) {
      videoError.value = error.value || 'Could not copy the video to the display SD card.'
      return
    }
    if (!saved.ready || !saved.filename) {
      videoStage.value = 'The display is still preparing this video. Open the SD Card page once it is ready to play.'
      return
    }
    videoStage.value = 'Starting video on the display...'
    if (await showSDCardFileOnDisplay(saved.filename)) {
      videoStage.value = 'Video is now playing on the display.'
    } else {
      videoError.value = error.value || 'Could not start the video on the display.'
    }
  } finally {
    showingVideoOnDisplay.value = false
  }
}

function confirmDeleteSavedVideo() {
  savedVideoContextMenu.value = false
  if (!contextMenuSavedVideo.value) return
  if (!confirmDeletion.value) {
    deleteSavedVideo()
    return
  }
  deleteSavedVideoDontAskAgain.value = false
  deleteSavedVideoDialog.value = true
}

async function deleteSavedVideo() {
  const savedVideo = contextMenuSavedVideo.value
  if (!savedVideo || deletingSavedVideo.value) return
  deletingSavedVideo.value = true
  metadataError.value = ''
  try {
    if (deleteSavedVideoDontAskAgain.value) await setDeleteConfirmation(false)
    const response = await fetch(`/saved-videos/${encodeURIComponent(savedVideo.id)}`, { method: 'DELETE' })
    if (!response.ok) {
      const body = await response.json().catch(() => ({}))
      throw new Error(body.detail || `Request failed (${response.status})`)
    }
    savedVideos.value = savedVideos.value.filter(video => video.id !== savedVideo.id)
    deleteSavedVideoDialog.value = false
    status.value = 'Video removed from the Creation Gallery.'
  } catch (requestError) {
    metadataError.value = `Could not remove this saved video: ${requestError.message}`
  } finally {
    deletingSavedVideo.value = false
  }
}

async function fetchDisplaySdCardReport() {
  if (!display.value?.connected) throw new Error('Choose one display first')
  const response = await fetch(selectedDisplayEndpoint('/display-sd-card'))
  if (!response.ok) throw new Error(`Request failed (${response.status})`)
  return response.json()
}

async function loadDisplaySdCard() {
  if (!display.value?.connected) {
    displaySdCard.value = { available: false, files: [] }
    return null
  }
  displaySdCardLoading.value = true
  try {
    displaySdCard.value = await fetchDisplaySdCardReport()
    return displaySdCard.value
  } catch {
    displaySdCard.value = { available: false, files: [] }
    return null
  } finally {
    displaySdCardLoading.value = false
  }
}

async function refreshDisplaySdCardInventory() {
  if (!activeDisplayOnline.value) throw new Error(activeDisplayCommandUnavailableMessage())
  displaySdCardLoading.value = true
  try {
    const previousReport = await fetchDisplaySdCardReport()
    displaySdCard.value = previousReport
    const previousVersion = Number(previousReport.report_version) || 0
    const response = await fetch(selectedDisplayEndpoint('/display-sd-card/refresh'), { method: 'POST' })
    if (!response.ok) {
      const body = await response.json().catch(() => ({}))
      throw new Error(body.detail || `Request failed (${response.status})`)
    }
    const command = await response.json()
    for (let attempt = 0; attempt < 40; attempt += 1) {
      await new Promise(resolve => window.setTimeout(resolve, 500))
      const commandResponse = await fetch(selectedDisplayCommandEndpoint(command.id))
      if (!commandResponse.ok) continue
      const result = await commandResponse.json()
      if (result.status === 'failed') throw new Error(result.detail || 'The display could not refresh its SD card list')
      if (result.status !== 'complete') continue
      const requiredVersion = Number(result.report_version) || previousVersion + 1
      for (let reportAttempt = 0; reportAttempt < 20; reportAttempt += 1) {
        const report = await fetchDisplaySdCardReport()
        displaySdCard.value = report
        if ((Number(report.report_version) || 0) >= requiredVersion) {
          if (!report.available) throw new Error('The display reported that no SD card is available')
          return report
        }
        await new Promise(resolve => window.setTimeout(resolve, 250))
      }
      throw new Error('The display confirmed the refresh, but has not sent its updated SD card list')
    }
    throw new Error('The display did not confirm the SD card refresh. Keep it connected and try again.')
  } finally {
    displaySdCardLoading.value = false
  }
}

async function refreshDisplaySdCard() {
  error.value = ''
  try {
    await refreshDisplaySdCardInventory()
  } catch (requestError) {
    error.value = `Could not refresh the display SD card: ${requestError.message}`
  }
}

function openGeneratePage() {
  navigate('generate')
}

function openActiveGeneration() {
  if (appBarStatus.value.page) navigate(appBarStatus.value.page)
}

function openDisplayHelp() {
  navigate('about')
}

function openSDCardPage() {
  navigate('sd-card')
  loadDisplaySdCard()
}

async function loadDisplayExperience() {
  if (!display.value?.connected) {
    displayExperience.value = { current_mode: 'server_controlled', offline_experience: 'slideshow', slideshow_interval_ms: 15000, slideshow_order: 'newest_first' }
    return
  }
  displayExperienceLoading.value = true
  displayExperienceError.value = ''
  try {
    const response = await fetch(selectedDisplayEndpoint('/display-experience'))
    if (!response.ok) throw new Error(`Request failed (${response.status})`)
    displayExperience.value = await response.json()
    displayExperienceIntervalSeconds.value = Number(displayExperience.value.slideshow_interval_ms) / 1000
  } catch (requestError) {
    displayExperienceError.value = `Could not load display experience: ${requestError.message}`
  } finally {
    displayExperienceLoading.value = false
  }
}

function openDisplayExperiencePage() {
  navigate('display-experience')
  loadDisplayExperience()
}

function navigate(nextPage) {
  page.value = nextPage
  if (compact.value) drawer.value = false
}

async function saveDisplayExperience() {
  if (!activeDisplayOnline.value) return
  displayExperienceSaving.value = true
  displayExperienceError.value = ''
  displayExperienceStatus.value = ''
  try {
    const response = await fetch(selectedDisplayEndpoint('/display-experience'), {
      method: 'PUT', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        offline_experience: displayExperience.value.offline_experience,
        slideshow_interval_ms: Math.round(Number(displayExperienceIntervalSeconds.value) * 1000),
        slideshow_order: displayExperience.value.slideshow_order
      })
    })
    if (!response.ok) {
      const body = await response.json().catch(() => ({}))
      throw new Error(body.detail || `Request failed (${response.status})`)
    }
    const command = await response.json()
    displayExperienceStatus.value = 'Saving to the display…'
    for (let attempt = 0; attempt < 30; attempt += 1) {
      await new Promise(resolve => window.setTimeout(resolve, 500))
      const commandResponse = await fetch(selectedDisplayCommandEndpoint(command.id))
      if (!commandResponse.ok) continue
      const result = await commandResponse.json()
      if (result.status === 'complete') {
        displayExperienceStatus.value = 'Display experience saved. The display will use it when ESPImageServer is unavailable.'
        await loadDisplayExperience()
        return
      }
      if (result.status === 'failed') throw new Error(result.detail || 'The display could not save this experience')
    }
    displayExperienceStatus.value = 'The display has not confirmed the save yet. Keep ESPImageServer open until it does.'
  } catch (requestError) {
    displayExperienceError.value = `Could not save display experience: ${requestError.message}`
  } finally {
    displayExperienceSaving.value = false
  }
}

async function previewDisplayExperience() {
  if (!activeDisplayOnline.value || displayExperiencePreviewing.value) return
  displayExperienceError.value = ''
  try {
    const response = await fetch(selectedDisplayEndpoint('/display-experience/preview'), {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        offline_experience: displayExperience.value.offline_experience,
        slideshow_interval_ms: Math.round(Number(displayExperienceIntervalSeconds.value) * 1000),
        slideshow_order: displayExperience.value.slideshow_order
      })
    })
    if (!response.ok) throw new Error(`Request failed (${response.status})`)
    displayExperiencePreviewing.value = true
    displayExperienceStatus.value = `${displayExperience.value.offline_experience === 'video_loop' ? 'Video loop' : 'Slideshow'} preview is starting on the display.`
  } catch (requestError) {
    displayExperienceError.value = `Could not start preview: ${requestError.message}`
  }
}

async function stopDisplayExperiencePreview() {
  if (!displayExperiencePreviewing.value) return
  displayExperiencePreviewing.value = false
  try {
    if (activeDisplayOnline.value) {
      await fetch(selectedDisplayEndpoint('/display-experience/preview'), { method: 'DELETE', keepalive: true })
    }
  } catch {
    // The firmware will return to server control on its next successful command poll.
  }
}

async function sendDisplaySdCardCommand(endpoint, method = 'POST', notify = true) {
  if (!activeDisplayOnline.value) {
    error.value = activeDisplayCommandUnavailableMessage()
    return false
  }
  error.value = ''
  try {
    const response = await fetch(selectedDisplayEndpoint(endpoint), { method })
    if (!response.ok) {
      const body = await response.json().catch(() => ({}))
      throw new Error(body.detail || `Request failed (${response.status})`)
    }
    if (notify) showSDCardSnackbar('Request sent to the display.')
    window.setTimeout(loadDisplaySdCard, 3500)
    return true
  } catch (requestError) {
    error.value = `Could not update the display SD card: ${requestError.message}`
    return false
  }
}

function displaySdCardMediaType(file) {
  return file?.type === 'video' || file?.name?.endsWith('.mjpeg') ? 'video' : 'image'
}

function confirmDeleteDisplaySdCardFile(file) {
  if (!file || deletingSdCardFile.value) return
  sdCardFileToDelete.value = file
  if (!confirmDeletion.value) {
    void deleteDisplaySdCardFile()
    return
  }
  deleteSdCardFileDontAskAgain.value = false
  deleteSdCardFileDialog.value = true
}

async function deleteDisplaySdCardFile() {
  const file = sdCardFileToDelete.value
  if (!file || deletingSdCardFile.value) return
  deletingSdCardFile.value = true
  try {
    if (deleteSdCardFileDontAskAgain.value) await setDeleteConfirmation(false)
    const deleted = await sendDisplaySdCardCommand(`/display-sd-card/files/${encodeURIComponent(file.name)}`, 'DELETE')
    if (deleted) deleteSdCardFileDialog.value = false
  } catch (requestError) {
    error.value = `Could not remove the display SD card ${displaySdCardMediaType(file)}: ${requestError.message}`
  } finally {
    deletingSdCardFile.value = false
  }
}

function confirmDeleteSelectedSdCardFiles() {
  const files = selectedSdCardFiles.value
  if (!files.length || deletingSdCardFile.value || deletingSdCardFiles.value) return
  sdCardFilesToDelete.value = [...files]
  if (!confirmDeletion.value) {
    void deleteSelectedDisplaySdCardFiles()
    return
  }
  deleteSdCardFilesDontAskAgain.value = false
  deleteSdCardFilesDialog.value = true
}

async function deleteSdCardFileAndWait(file) {
  const response = await fetch(
    selectedDisplayEndpoint(`/display-sd-card/files/${encodeURIComponent(file.name)}`),
    { method: 'DELETE' }
  )
  if (!response.ok) {
    const body = await response.json().catch(() => ({}))
    throw new Error(body.detail || `Request failed (${response.status})`)
  }
  const command = await response.json()
  for (let attempt = 0; attempt < 30; attempt += 1) {
    await new Promise(resolve => window.setTimeout(resolve, 500))
    const commandResponse = await fetch(selectedDisplayCommandEndpoint(command.id))
    if (!commandResponse.ok) throw new Error(`Could not check display status (${commandResponse.status})`)
    const result = await commandResponse.json()
    if (result.status === 'complete') return
    if (result.status === 'failed') throw new Error(result.detail || `The display could not delete ${file.name}`)
  }
  throw new Error(`The display has not confirmed deleting ${file.name}`)
}

function removeSdCardFilesFromInventory(files) {
  const deletedNames = new Set(files.map(file => file.name))
  displaySdCard.value = {
    ...displaySdCard.value,
    files: displaySdCardFiles().filter(file => !deletedNames.has(file.name))
  }
  selectedSdCardFileNames.value = selectedSdCardFileNames.value.filter(name => !deletedNames.has(name))
}

async function deleteSelectedDisplaySdCardFiles() {
  const files = sdCardFilesToDelete.value
  if (!files.length || deletingSdCardFiles.value) return
  deletingSdCardFiles.value = true
  error.value = ''
  const deletedFiles = []
  try {
    if (deleteSdCardFilesDontAskAgain.value) await setDeleteConfirmation(false)
    for (const file of files) {
      await deleteSdCardFileAndWait(file)
      deletedFiles.push(file)
    }
    removeSdCardFilesFromInventory(deletedFiles)
    deleteSdCardFilesDialog.value = false
    showSDCardSnackbar(`${deletedFiles.length} ${deletedFiles.length === 1 ? 'file' : 'files'} removed from the display SD card.`)
    window.setTimeout(loadDisplaySdCard, 750)
  } catch (requestError) {
    if (deletedFiles.length) removeSdCardFilesFromInventory(deletedFiles)
    error.value = `Could not remove all selected SD card files: ${requestError.message}`
  } finally {
    deletingSdCardFiles.value = false
  }
}

async function showSDCardFileOnDisplay(filename) {
  if (displayingSdCardFile.value) return false
  const isVideo = filename.endsWith('.mjpeg')
  const fileLabel = isVideo ? 'video' : 'image'
  displayingSdCardFile.value = filename
  error.value = ''
  status.value = ''
  try {
    if (!activeDisplayOnline.value) throw new Error(activeDisplayCommandUnavailableMessage())
    const response = await fetch(
      selectedDisplayEndpoint(`/display-sd-card/files/${encodeURIComponent(filename)}/display`),
      { method: 'POST' }
    )
    if (!response.ok) {
      const body = await response.json().catch(() => ({}))
      throw new Error(body.detail || `Request failed (${response.status})`)
    }
    const command = await response.json()
    for (let attempt = 0; attempt < 30; attempt += 1) {
      await new Promise(resolve => window.setTimeout(resolve, 500))
      const commandResponse = await fetch(selectedDisplayCommandEndpoint(command.id))
      if (!commandResponse.ok) throw new Error(`Could not check display status (${commandResponse.status})`)
      const result = await commandResponse.json()
      if (result.status === 'complete') {
        showSDCardSnackbar(isVideo ? 'Video is now playing from the SD card.' : 'Image is now showing on the display.')
        return true
      }
      if (result.status === 'failed') throw new Error(result.detail || `The display could not show this ${fileLabel}`)
    }
    showSDCardSnackbar(`The display is still processing the ${fileLabel}.`)
    return true
  } catch (requestError) {
    error.value = `Could not show ${fileLabel} on the display: ${requestError.message}`
    return false
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
    videoJpegQuality.value = settings.video_jpeg_quality
    autoSaveImages.value = settings.auto_save_images !== false
    autoSaveVideos.value = settings.auto_save_videos !== false
    confirmDeletion.value = settings.confirm_deletion !== false
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
        video_jpeg_quality: Number(videoJpegQuality.value),
        auto_save_images: autoSaveImages.value,
        auto_save_videos: autoSaveVideos.value,
        confirm_deletion: confirmDeletion.value
      })
    })
    if (!response.ok) {
      const body = await response.json().catch(() => ({}))
      throw new Error(body.detail || `Request failed (${response.status})`)
    }
    const settings = await response.json()
    imageLibraryLocation.value = settings.image_library_location
    jpegQuality.value = settings.jpeg_quality
    videoJpegQuality.value = settings.video_jpeg_quality
    autoSaveImages.value = settings.auto_save_images !== false
    autoSaveVideos.value = settings.auto_save_videos !== false
    confirmDeletion.value = settings.confirm_deletion !== false
    await loadSavedImages()
    settingsStatus.value = 'Settings saved. Image and video quality settings apply to future exports.'
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

async function setAutoSaveVideos(value) {
  const previousValue = autoSaveVideos.value
  autoSaveVideos.value = value
  autoSaveVideoSaving.value = true
  videoError.value = ''
  try {
    const response = await fetch('/app-settings', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ auto_save_videos: value })
    })
    if (!response.ok) {
      const body = await response.json().catch(() => ({}))
      throw new Error(body.detail || `Request failed (${response.status})`)
    }
    const settings = await response.json()
    autoSaveVideos.value = settings.auto_save_videos !== false
  } catch (requestError) {
    autoSaveVideos.value = previousValue
    videoError.value = `Could not update automatic video saving: ${requestError.message}`
  } finally {
    autoSaveVideoSaving.value = false
  }
}

async function setDeleteConfirmation(value) {
  const response = await fetch('/app-settings', {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ confirm_deletion: value })
  })
  if (!response.ok) {
    const body = await response.json().catch(() => ({}))
    throw new Error(body.detail || `Request failed (${response.status})`)
  }
  const settings = await response.json()
  confirmDeletion.value = settings.confirm_deletion !== false
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
  if (compact.value) drawer.value = false
  metadataPane.value = true
  await loadSavedImages()
  await loadDisplaySdCard()
}

async function refreshCreationLibrarySdCardStatus() {
  metadataError.value = ''
  try {
    await refreshDisplaySdCardInventory()
  } catch (requestError) {
    metadataError.value = `Could not refresh the display SD card status: ${requestError.message}`
  }
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
    negativePrompt: negativePrompt.value,
    rotation: displayRotation.value,
    display: display.value?.connected
      ? { name: display.value.name, width: display.value.width, height: display.value.height }
      : null
  }
}

async function useRecalledSettings() {
  await useSavedImageSettings(recalledMetadata.value, 'all')
}

async function useSelectedSavedImageSettings() {
  if (!selectedSavedImage.value) return
  await useSavedImageSettings(selectedSavedImage.value.metadata, 'all')
}

async function showSavedImageOnDisplay(savedImage = selectedSavedImage.value) {
  if (!savedImage || !hasDisplayTargets.value || showingSavedImageOnDisplay.value) return
  showingSavedImageOnDisplay.value = true
  error.value = ''
  try {
    const response = await fetch(`/saved-images/${encodeURIComponent(savedImage.id)}/display`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        display_ids: selectedTargetDisplayIds.value
      })
    })
    if (!response.ok) {
      const body = await response.json().catch(() => ({}))
      throw new Error(body.detail || `Could not send image to display (${response.status})`)
    }
    status.value = activeDisplayOnline.value
      ? `Selected image is ready for ${display.value?.name}.`
      : `Selected image is ready for ${display.value?.name}; it will appear when the display reconnects.`
  } catch (requestError) {
    error.value = `Could not show the saved image on your display: ${requestError.message}`
  } finally {
    showingSavedImageOnDisplay.value = false
  }
}

function showSavedImageActions(savedImage, position) {
  contextMenuSavedImage.value = savedImage
  savedImageContextMenuPosition.value = position
  savedImageContextMenu.value = false
  window.requestAnimationFrame(() => {
    savedImageContextMenu.value = true
  })
}

function openSavedImageContextMenu(event, savedImage) {
  event.preventDefault()
  showSavedImageActions(savedImage, [event.clientX, event.clientY])
}

function openSavedImageActions(event, savedImage) {
  const bounds = event.currentTarget.getBoundingClientRect()
  showSavedImageActions(savedImage, [bounds.right, bounds.bottom])
}

function toggleImageLibraryView() {
  imageLibraryView.value = imageLibraryView.value === 'thumbnails' ? 'list' : 'thumbnails'
}

function startImageLibraryResize(event) {
  if (compact.value) return
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
  if (!contextMenuSavedImage.value) return
  if (!confirmDeletion.value) {
    deleteSavedImage()
    return
  }
  deleteSavedImageDontAskAgain.value = false
  deleteSavedImageDialog.value = true
}

async function deleteSavedImage() {
  const savedImage = contextMenuSavedImage.value
  if (!savedImage || deletingSavedImage.value) return
  deletingSavedImage.value = true
  metadataError.value = ''
  try {
    if (deleteSavedImageDontAskAgain.value) await setDeleteConfirmation(false)
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
  const requestId = ++imagePreviewRequestId
  try {
    const response = await fetch(`/saved-images/${encodeURIComponent(savedImage.id)}/image`)
    if (!response.ok) throw new Error(`Request failed (${response.status})`)
    const shown = await updateImagePreview(await response.blob(), {
      requestId,
      metadata: savedImage.metadata,
      savedToLibrary: true,
      savedImage
    })
    if (!shown) return
    recalledMetadata.value = savedImage.metadata
    status.value = 'Previewing saved image. Generator settings and the display are unchanged.'
    page.value = 'generate'
    if (!metadataPanePinned.value) metadataPane.value = false
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
  if (!activeDisplayOnline.value || savingToDisplaySdCard.value) return
  savingToDisplaySdCard.value = true
  error.value = ''
  status.value = ''
  try {
    status.value = 'Checking the display SD card for this image...'
    await refreshDisplaySdCardInventory()
    const endpoint = savedImage
      ? `${selectedDisplayEndpoint('/display-commands/save-saved-image')}/${encodeURIComponent(savedImage.id)}`
      : selectedDisplayEndpoint('/display-commands/save-latest')
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
      const commandResponse = await fetch(selectedDisplayCommandEndpoint(command.id))
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

async function fetchGenerationResponse(url) {
  // A completed job remains on the server even when a browser or ESP32 TCP
  // connection drops. Keep polling through transient connection resets rather
  // than telling the user their generation failed.
  for (;;) {
    try {
      const response = await fetch(url)
      if (response.ok || response.status < 500) return response
    } catch {
      // Connection resets are retried below.
    }
    await new Promise(resolve => window.setTimeout(resolve, 1500))
  }
}

function showQueueAddedFeedback(kind, queuePosition) {
  generationQueueSnackbarMessage.value = `${kind} added to the queue${queuePosition ? ` · position ${queuePosition}` : ''}.`
  generationQueueSnackbar.value = true
}

async function generate() {
  const alreadyShowingImageProgress = generating.value
  generating.value = true
  error.value = ''
  status.value = ''
  if (!alreadyShowingImageProgress) {
    generationProgress.value = 0
    generationStage.value = 'Preparing image generation...'
  }
  let job
  try {
    if (!models.value.some(model => model.id === activeModelId.value)) throw new Error('Choose an image model before generating.')
    if (!alreadyShowingImageProgress) generationStage.value = 'Adding image to the queue...'
    const response = await fetch('/generation-jobs', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        prompt: prompt.value,
        model_id: activeModelId.value,
        negative_prompt: negativePrompt.value || null,
        steps: Number(steps.value),
        seed: seed.value === '' ? null : Number(seed.value),
        ...(hasDisplayTargets.value
          ? { display_ids: selectedTargetDisplayIds.value }
          : {})
      })
    })
    if (!response.ok) {
      const body = await response.json().catch(() => ({}))
      throw new Error(body.detail || `Request failed (${response.status})`)
    }
    job = await response.json()
    if (!activeJobId.value) activeJobId.value = job.id
    activeImageJobRunning.value = ['queued', 'running', 'cancelling'].includes(job.status)
    status.value = `Image job added to the queue${job.queue_position ? ` (position ${job.queue_position})` : ''}.`
    showQueueAddedFeedback('Image', job.queue_position)
    await loadGenerationQueue()
    let currentJob = job
    while (!['complete', 'failed', 'cancelled'].includes(currentJob.status)) {
      await new Promise(resolve => window.setTimeout(resolve, 350))
      const statusResponse = await fetchGenerationResponse(`/generation-jobs/${job.id}`)
      if (!statusResponse.ok) throw new Error(`Request failed (${statusResponse.status})`)
      currentJob = await statusResponse.json()
      if (['running', 'cancelling'].includes(currentJob.status) && !activeJobId.value) activeJobId.value = job.id
      if (activeJobId.value === job.id) {
        activeImageJobRunning.value = ['running', 'cancelling'].includes(currentJob.status)
        generationProgress.value = currentJob.progress
        generationStage.value = currentJob.steps ? `${currentJob.stage} — Step ${currentJob.step} of ${currentJob.steps}` : currentJob.stage
      }
    }
    if (currentJob.status === 'cancelled') {
      status.value = 'Image generation cancelled.'
      return
    }
    if (currentJob.status === 'failed') throw new Error(currentJob.error || 'Image generation failed')
    if (activeJobId.value === job.id) generationStage.value = 'Image ready. Loading it into the preview...'
    const imageResponse = await fetchGenerationResponse(`/generation-jobs/${job.id}/image`)
    if (!imageResponse.ok) throw new Error(`Request failed (${imageResponse.status})`)
    const metadata = currentJob.metadata || buildGenerationMetadata()
    if (activeJobId.value === job.id) generationStage.value = 'Preparing the display preview...'
    await updateImagePreview(await imageResponse.blob(), {
      jobId: job.id,
      metadata,
      savedToLibrary: autoSaveImages.value
    })
    if (activeJobId.value === job.id) generationStage.value = 'Refreshing your Creation Gallery...'
    await loadSavedImages()
    const deliveryMessage = display.value?.connected && !activeDisplayOnline.value
      ? `${display.value.name} is offline; it will request this image when it reconnects.`
      : 'Your ESP32 display will pick it up shortly.'
    status.value = autoSaveImages.value
      ? `Image ready and saved. ${deliveryMessage}`
      : 'Image ready. Automatic saving is off—use Save image to computer to keep this image.'
  } catch (requestError) {
    if (requestError.message === 'Image generation cancelled.') {
      status.value = requestError.message
    } else {
      error.value = `Could not generate the image: ${requestError.message}`
      status.value = ''
    }
  } finally {
    if (!job || activeJobId.value === job.id) {
      generating.value = false
      cancelling.value = false
      activeJobId.value = ''
      activeImageJobRunning.value = false
      generationProgress.value = 0
      generationStage.value = ''
    }
  }
}

async function cancelGeneration() {
  if (cancelling.value) return
  cancelling.value = true
  error.value = ''
  if (!activeJobId.value) {
    cancelling.value = false
    return
  }
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
  const frames = Number(videoFrames.value)
  if (!Number.isInteger(frames) || frames < 9 || frames > 249 || (frames - 1) % 8 !== 0) {
    videoError.value = 'Choose a duration preset or enter an advanced frame count from 9 to 249 in steps of 8.'
    return
  }
  const alreadyShowingVideoProgress = generatingVideo.value
  generatingVideo.value = true
  videoError.value = ''
  if (!alreadyShowingVideoProgress) {
    videoProgress.value = 0
    videoStage.value = 'Starting video generation. The selected model will download first if it is not already on this computer...'
  }
  let job
  try {
    const response = await fetch('/video-generation-jobs', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        prompt: videoPrompt.value,
        num_frames: frames,
        fps: Number(videoFps.value),
        steps: Number(videoSteps.value),
        model_id: videoModelId.value,
        seed: videoSeed.value === '' ? null : Number(videoSeed.value),
        source_image_id: videoSourceImage.value?.id || null,
        ...(hasDisplayTargets.value
          ? { display_ids: selectedTargetDisplayIds.value }
          : {})
      })
    })
    if (!response.ok) {
      const body = await response.json().catch(() => ({}))
      throw new Error(body.detail || `Request failed (${response.status})`)
    }
    job = await response.json()
    if (['running', 'cancelling'].includes(job.status) && !activeVideoJobId.value) {
      activeVideoJobId.value = job.id
      activeVideoJobRunning.value = true
    }
    if (!alreadyShowingVideoProgress) videoStage.value = `Video job added to the queue${job.queue_position ? ` (position ${job.queue_position})` : ''}.`
    showQueueAddedFeedback('Video', job.queue_position)
    await loadGenerationQueue()
    if (cancelVideoOnStart.value) {
      cancelVideoOnStart.value = false
      await cancelVideoGeneration()
    }
    let currentJob = job
    while (!['complete', 'failed', 'cancelled'].includes(currentJob.status)) {
      await new Promise(resolve => window.setTimeout(resolve, 500))
      const statusResponse = await fetchGenerationResponse(`/video-generation-jobs/${job.id}`)
      if (!statusResponse.ok) throw new Error(`Request failed (${statusResponse.status})`)
      currentJob = await statusResponse.json()
      if (['running', 'cancelling'].includes(currentJob.status) && !activeVideoJobId.value) activeVideoJobId.value = job.id
      if (activeVideoJobId.value === job.id) {
        activeVideoJobRunning.value = ['running', 'cancelling'].includes(currentJob.status)
        videoProgress.value = currentJob.progress
        videoStage.value = currentJob.steps ? `${currentJob.stage} — Step ${currentJob.step} of ${currentJob.steps}` : currentJob.stage
      }
    }
    if (currentJob.status === 'cancelled') {
      videoStage.value = 'Video generation cancelled.'
      return
    }
    if (currentJob.status === 'failed') throw new Error(currentJob.error || 'Video generation failed')
    if (activeVideoJobId.value === job.id) videoStage.value = 'Video ready. Loading it into the preview...'
    const videoResponse = await fetchGenerationResponse(`/video-generation-jobs/${job.id}/video`)
    if (!videoResponse.ok) throw new Error(`Request failed (${videoResponse.status})`)
    if (activeVideoJobId.value === job.id) videoStage.value = 'Preparing video preview...'
    const autoSaved = currentJob.metadata?.auto_saved === true
    completedVideoSavedId.value = autoSaved ? currentJob.metadata?.saved_video_id || '' : ''
    await updateVideoPreview(await videoResponse.blob(), { jobId: job.id, savedToLibrary: autoSaved })
    if (autoSaved) await loadSavedVideos()
    if (activeVideoJobId.value === job.id) videoStage.value = autoSaved
      ? 'Video ready and saved to your Creation Gallery.'
      : 'Video ready. Save it to your Creation Gallery or download it below.'
  } catch (requestError) {
    videoError.value = `Could not generate the video: ${requestError.message}`
    videoStage.value = ''
  } finally {
    if (activeVideoJobId.value === job?.id) {
      generatingVideo.value = false
      cancellingVideo.value = false
      cancelVideoOnStart.value = false
      activeVideoJobId.value = ''
      activeVideoJobRunning.value = false
    }
  }
}

async function saveVideoToCreationLibrary() {
  if (completedVideoSavedId.value) return completedVideoSavedId.value
  if (!completedVideoJobId.value || savingVideoToCreationLibrary.value || videoSavedToCreationLibrary.value) return ''
  savingVideoToCreationLibrary.value = true
  try {
    const response = await fetch(`/video-generation-jobs/${completedVideoJobId.value}/save`, { method: 'POST' })
    if (!response.ok) {
      const body = await response.json().catch(() => ({}))
      throw new Error(body.detail || `Request failed (${response.status})`)
    }
    const savedVideo = await response.json()
    completedVideoSavedId.value = savedVideo.id
    videoSavedToCreationLibrary.value = true
    videoStage.value = 'Video saved to your Creation Gallery.'
    await loadSavedVideos()
    return savedVideo.id
  } catch (requestError) {
    videoError.value = `Could not save the video to the Creation Gallery: ${requestError.message}`
    return ''
  } finally {
    savingVideoToCreationLibrary.value = false
  }
}

async function saveCompletedVideoToDisplaySdCard() {
  if (!activeDisplayOnline.value || savingVideoToDisplaySdCard.value) return
  let videoId = completedVideoSavedId.value
  if (!videoId) {
    videoStage.value = 'Saving video to your Creation Gallery before sending it to the display...'
    videoId = await saveVideoToCreationLibrary()
    if (!videoId) return
  }
  videoStage.value = 'Copying video to the display SD card for offline playback...'
  const saved = await saveVideoToDisplaySdCard(videoId)
  if (saved?.ready) videoStage.value = 'Video saved to the display SD card for offline playback.'
  else if (saved) videoStage.value = 'The display is still preparing the video for offline playback.'
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
  await loadVideoModels()
  await loadSavedImages()
  await loadSavedVideos()
  await loadAppSettings()
  await loadGenerationQueue()
  await clearDiagnostics()
  if (metadataPanePinned.value && !compact.value) metadataPane.value = true
  statusTimer = window.setInterval(() => {
    loadServerStatus()
    loadDisplay()
    loadModels()
    loadVideoModels()
    loadDisplaySdCard()
    loadGenerationQueue()
    loadDiagnostics()
  }, 5000)
})

onUnmounted(() => {
  window.clearInterval(statusTimer)
  window.clearInterval(consoleRefreshTimer)
  if (imageUrl.value) URL.revokeObjectURL(imageUrl.value)
  if (previewUrl.value) URL.revokeObjectURL(previewUrl.value)
  if (videoUrl.value) URL.revokeObjectURL(videoUrl.value)
})
</script>

<template>
  <v-app class="app-root">
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
    <v-snackbar v-model="generationQueueSnackbar" color="success" location="bottom" timeout="5000">
      <div class="d-flex align-center ga-2">
        <v-icon icon="mdi-check-circle" />
        <span>{{ generationQueueSnackbarMessage }}</span>
      </div>
      <template #actions>
        <v-btn variant="text" @click="page = 'queue'; generationQueueSnackbar = false">View queue</v-btn>
      </template>
    </v-snackbar>

    <v-app-bar name="primary-app-bar" order="-1" color="surface" border elevation="2" class="app-bar">
      <v-app-bar-nav-icon :aria-label="drawer ? 'Close navigation menu' : 'Open navigation menu'" :title="drawer ? 'Close navigation menu' : 'Open navigation menu'" @click="drawer = !drawer" />
      <v-avatar :image="logoImageUrl" size="36" class="mr-3" />
      <v-chip class="app-bar__activity-chip mr-2" :color="appBarStatus.color" variant="tonal" :prepend-icon="appBarStatus.icon" :link="Boolean(appBarStatus.page)" :title="appBarStatus.page ? 'Open active generation' : appBarStatus.label" @click="openActiveGeneration">
        <span>{{ compact ? appBarStatus.compactLabel : appBarStatus.label }}</span>
      </v-chip>
      <v-menu v-model="displayPickerOpen" location="bottom start" :close-on-content-click="true">
        <template #activator="{ props }">
          <v-chip v-bind="props" class="app-bar__display-chip" :color="activeDisplayOnline ? 'info' : 'warning'" variant="tonal" :prepend-icon="activeDisplayOnline ? 'mdi-monitor-check' : display?.connected ? 'mdi-monitor-off' : 'mdi-monitor-dashboard'" :aria-label="`${displayTargetLabel}. Open display chooser.`" :title="`${displayTargetLabel}. Choose active display.`">
            <span class="app-bar__display-label">{{ compact ? compactDisplayLabel : displayTargetLabel }}</span>
            <v-icon class="app-bar__display-chevron" size="18">{{ displayPickerOpen ? 'mdi-menu-up' : 'mdi-menu-down' }}</v-icon>
          </v-chip>
        </template>
        <v-card min-width="300" max-width="420">
          <v-card-title class="text-subtitle-1">Active display</v-card-title>
          <v-card-subtitle>{{ activeDisplayOnline ? 'Images, videos, and display controls use this screen.' : 'This display is offline. Image updates wait until it reconnects.' }}</v-card-subtitle>
          <v-list v-if="displays.length" density="comfortable" class="mt-2">
            <v-list-item
              v-for="target in displays"
              :key="target.id"
              :active="target.id === activeDisplayId"
              @click="selectActiveDisplay(target.id)"
            >
              <template #prepend><v-icon :color="target.online ? 'success' : 'warning'">{{ target.online ? 'mdi-monitor-check' : 'mdi-monitor-off' }}</v-icon></template>
              <v-list-item-title>{{ target.name }}</v-list-item-title>
              <v-list-item-subtitle>{{ target.width }} × {{ target.height }} · v{{ target.firmware_version }} · {{ target.online ? 'Online' : 'Last seen earlier' }}</v-list-item-subtitle>
              <template #append><v-icon v-if="target.id === activeDisplayId" color="primary">mdi-check</v-icon></template>
            </v-list-item>
          </v-list>
          <v-card-text v-else class="pt-2">
            <v-alert type="info" variant="tonal" density="compact">
              Turn on an ESP32 display to choose it here.
            </v-alert>
          </v-card-text>
          <v-card-actions>
            <v-spacer />
            <v-btn variant="text" @click="displays.length ? openDisplayExperiencePage() : openDisplayHelp()">Display settings</v-btn>
          </v-card-actions>
        </v-card>
      </v-menu>
      <v-spacer />
      <v-btn size="x-large" icon="mdi-image-text" variant="text" aria-label="Open Creation Library" title="Open Creation Library" @click="openMetadataPane" />
    </v-app-bar>

    <v-navigation-drawer v-model="drawer" width="272" border :temporary="compact">
      <v-list-item class="py-4" subtitle="Local AI image & video generation">
        <template #title>
          <div class="d-flex align-baseline ga-2">
            <span>ESPImageServer</span>
            <span v-if="serverInfo?.version" class="text-caption text-medium-emphasis">v{{ serverInfo.version }}</span>
          </div>
        </template>
      </v-list-item>
      <v-divider />
      <v-list nav density="comfortable">
        <v-list-item prepend-icon="mdi-image-plus" title="Generate image" :active="page === 'generate'" @click="openGeneratePage" />
        <v-list-item prepend-icon="mdi-movie-open-outline" title="Generate video" :active="page === 'video'" @click="navigate('video')" />
        <v-list-item prepend-icon="mdi-image-text" title="Creation Library" :active="metadataPane" @click="openMetadataPane" />
        <v-list-item prepend-icon="mdi-brain" title="Models" :active="page === 'models'" @click="navigate('models')" />
        <v-list-item prepend-icon="mdi-monitor-dashboard" title="Display Experience" :active="page === 'display-experience'" @click="openDisplayExperiencePage" />
        <v-list-item prepend-icon="mdi-sd" title="SD Card" :active="page === 'sd-card'" @click="openSDCardPage" />
        <v-list-item prepend-icon="mdi-cog-outline" title="Settings" :active="page === 'settings'" @click="navigate('settings')" />
        <v-list-item prepend-icon="mdi-information-outline" title="About" :active="page === 'about'" @click="navigate('about')" />
      </v-list>
      <template #append>
        <v-divider />
        <v-list nav density="comfortable">
          <v-list-item prepend-icon="mdi-format-list-numbered" title="Queue" :active="page === 'queue'" @click="navigate('queue')">
            <template #append><v-chip v-if="activeGenerationQueue.length" color="primary" size="x-small" variant="tonal" title="Active generation jobs">{{ activeGenerationQueue.length }}</v-chip></template>
          </v-list-item>
          <v-list-item prepend-icon="mdi-text-box-outline" title="Diagnostics" :active="page === 'diagnostics'" @click="navigate('diagnostics')" />
        </v-list>
      </template>
    </v-navigation-drawer>

    <v-navigation-drawer v-if="metadataPane" v-model="metadataPane" class="creation-library-drawer" location="right" :width="compact ? '100%' : imageLibraryWidth" :permanent="metadataPanePinned && !compact" :temporary="creationLibraryTemporary" :scrim="creationLibraryTemporary" border>
      <div
        v-if="!compact"
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
        <v-btn v-if="!compact" :icon="metadataPanePinned ? 'mdi-pin' : 'mdi-pin-outline'" variant="text" :aria-label="metadataPanePinned ? 'Unpin image library pane' : 'Pin image library pane'" :title="metadataPanePinned ? 'Unpin Creation Library' : 'Pin Creation Library open'" @click="toggleMetadataPanePin" />
        <v-btn icon="mdi-close" variant="text" aria-label="Close Creation Library" title="Close Creation Library" @click="closeMetadataPane" />
      </div>
      <v-divider />
      <div class="creation-library-drawer__body pa-4">
        <v-alert :type="display?.connected ? 'info' : 'warning'" variant="tonal" density="compact" class="display-context-bar mb-4" :prepend-icon="activeDisplayOnline ? 'mdi-monitor-check' : 'mdi-monitor-off'">
          <strong>Working with:</strong> {{ displayManagementLabel }}
          <div class="text-caption mt-1">New display and SD-card actions use this active display.</div>
        </v-alert>
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
        <div class="d-flex align-center flex-wrap ga-2 mb-3">
          <v-chip v-if="creationSdCardInventoryConfirmed && displaySdCard.available" size="small" color="success" variant="tonal" prepend-icon="mdi-sd">
            SD card status reported
          </v-chip>
          <v-chip v-else-if="creationSdCardInventoryConfirmed" size="small" color="warning" variant="tonal" prepend-icon="mdi-sd-off">
            No SD card reported
          </v-chip>
          <v-chip v-else size="small" variant="tonal" prepend-icon="mdi-help-circle-outline">
            SD card status not checked
          </v-chip>
          <v-btn size="small" variant="text" prepend-icon="mdi-refresh" :loading="displaySdCardLoading" @click="refreshCreationLibrarySdCardStatus">
            Refresh SD status
          </v-btn>
        </div>
        <div v-if="displaySdCard.reported_at" class="text-caption text-medium-emphasis mb-3">
          Last reported by the display: {{ formatDateTime(displaySdCard.reported_at) }}
        </div>
        <v-row dense class="mb-3">
          <v-col cols="12" md="4">
            <v-select
              v-model="creationModelFilter"
              :items="creationModelOptions"
              label="Filter by model"
              prepend-inner-icon="mdi-brain"
              clearable
              hide-details
              density="compact"
              variant="outlined"
            />
          </v-col>
          <v-col cols="12" md="4">
            <v-select
              v-model="creationDisplayFilter"
              :items="creationDisplayOptions"
              label="Filter by display"
              prepend-inner-icon="mdi-monitor-dashboard"
              clearable
              hide-details
              density="compact"
              variant="outlined"
            />
          </v-col>
          <v-col cols="12" md="4">
            <v-select
              v-model="creationSdCardFilter"
              :items="creationSdCardFilterOptions"
              label="Filter by SD card"
              prepend-inner-icon="mdi-sd"
              clearable
              :disabled="!creationSdCardInventoryConfirmed"
              hide-details
              density="compact"
              variant="outlined"
            />
          </v-col>
        </v-row>
        <v-progress-linear v-if="savedImagesLoading" indeterminate color="primary" class="mb-3" />
        <div v-if="!savedImagesLoading && filteredSavedImages.length && imageLibraryView === 'thumbnails'" class="saved-image-library">
          <section v-for="group in savedImageGroups" :key="group.modelName" class="saved-image-group">
            <div class="text-caption font-weight-bold text-medium-emphasis mb-2">{{ group.modelName }}</div>
            <div class="saved-image-grid" :style="{ '--thumbnail-size': `${imageLibraryThumbnailSize}px` }">
              <v-tooltip v-for="savedImage in group.images" :key="savedImage.id" location="end" max-width="260" open-delay="800">
                <template #activator="{ props }">
                  <v-card v-bind="props" class="saved-image-thumbnail" variant="outlined" @click="openSavedImage(savedImage)" @contextmenu="openSavedImageContextMenu($event, savedImage)">
                    <v-img :src="`/saved-images/${encodeURIComponent(savedImage.id)}/thumbnail`" aspect-ratio="1.33" cover />
                    <v-chip v-if="creationIsOnDisplaySdCard(savedImage, 'image')" class="saved-image-thumbnail__sd-status" size="x-small" color="success" variant="flat" prepend-icon="mdi-sd" @click.stop>On SD card</v-chip>
                    <v-btn class="saved-image-thumbnail__more" icon="mdi-dots-vertical" size="small" color="surface" variant="flat" elevation="3" aria-label="More actions for saved image" title="More actions" @pointerdown.stop @click.stop="openSavedImageActions($event, savedImage)" />
                    <div class="pa-2 text-caption saved-image-thumbnail__prompt">{{ savedImage.metadata?.prompt || 'Generated image' }}</div>
                  </v-card>
                </template>
                <div class="text-body-2 saved-creation-tooltip">
                  <div class="font-weight-bold">{{ savedImage.metadata?.model?.name || 'ESPImageServer' }}</div>
                  <div class="saved-creation-tooltip__prompt">{{ savedImage.metadata?.prompt || 'Generated image' }}</div>
                  <div v-if="creationIsOnDisplaySdCard(savedImage, 'image')" class="text-caption mt-1"><v-icon size="14">mdi-sd</v-icon> {{ creationSdCardLabel(savedImage, 'image') }}</div>
                  <div v-if="formatGenerationTime(savedImage.metadata?.generation_time_seconds)" class="text-caption mt-1">Generated in {{ formatGenerationTime(savedImage.metadata?.generation_time_seconds) }}</div>
                </div>
              </v-tooltip>
            </div>
          </section>
        </div>
        <v-list v-if="!savedImagesLoading && filteredSavedImages.length && imageLibraryView === 'list'" class="saved-image-library saved-image-list" density="compact" lines="two">
          <v-list-item v-for="savedImage in filteredSavedImages" :key="savedImage.id" prepend-icon="mdi-image" @click="openSavedImage(savedImage)" @contextmenu="openSavedImageContextMenu($event, savedImage)">
            <v-list-item-title>{{ savedImage.metadata?.prompt || 'Generated image' }}</v-list-item-title>
            <template #append>
              <v-chip v-if="creationIsOnDisplaySdCard(savedImage, 'image')" size="x-small" color="success" variant="tonal" prepend-icon="mdi-sd" class="mr-1">On SD card</v-chip>
              <v-btn icon="mdi-dots-vertical" size="small" variant="text" aria-label="More actions for saved image" title="More actions" @pointerdown.stop @click.stop="openSavedImageActions($event, savedImage)" />
            </template>
            <v-list-item-subtitle>{{ savedImage.metadata?.model?.name || 'ESPImageServer' }} · {{ new Date(savedImage.created_at).toLocaleString() }}</v-list-item-subtitle>
          </v-list-item>
        </v-list>
        <div v-if="!savedImagesLoading && !savedImages.length && !savedVideos.length" class="text-body-2 text-medium-emphasis">No generated images or videos have been saved yet.</div>
        <div v-else-if="!savedImagesLoading && !filteredCreationsCount" class="text-body-2 text-medium-emphasis">No saved creations match these filters.</div>
        <template v-if="filteredSavedVideos.length && imageLibraryView === 'thumbnails'">
          <section v-for="group in savedVideoGroups" :key="group.modelName" class="saved-image-group mt-6">
            <div class="text-caption font-weight-bold text-medium-emphasis mb-2">{{ group.modelName }}</div>
            <div class="saved-image-grid" :style="{ '--thumbnail-size': `${imageLibraryThumbnailSize}px` }">
            <v-tooltip v-for="savedVideo in group.videos" :key="savedVideo.id" location="end" max-width="260" open-delay="800">
              <template #activator="{ props }">
                <v-card v-bind="props" class="saved-image-thumbnail" variant="outlined" @click="openSavedVideo(savedVideo)" @contextmenu="openSavedVideoContextMenu($event, savedVideo)">
                  <v-img v-if="savedVideo.thumbnail_filename" :src="`/saved-videos/${encodeURIComponent(savedVideo.id)}/thumbnail`" aspect-ratio="1.33" cover />
                  <v-sheet v-else class="d-flex align-center justify-center" height="120"><v-icon size="40">mdi-movie-open-outline</v-icon></v-sheet>
                  <v-chip v-if="creationIsOnDisplaySdCard(savedVideo, 'video')" class="saved-image-thumbnail__sd-status" size="x-small" color="success" variant="flat" prepend-icon="mdi-sd" @click.stop>On SD card</v-chip>
                  <v-btn class="saved-image-thumbnail__more" icon="mdi-dots-vertical" size="small" color="surface" variant="flat" elevation="3" aria-label="More actions for saved video" title="More actions" @pointerdown.stop @click.stop="openSavedVideoActions($event, savedVideo)" />
                  <div class="pa-2 text-caption saved-image-thumbnail__prompt">{{ savedVideo.metadata?.prompt || 'Generated video' }}</div>
                </v-card>
              </template>
              <div class="text-body-2 saved-creation-tooltip">
                <div class="font-weight-bold">{{ savedVideo.metadata?.model?.name || 'LTX-Video' }}</div>
                <div class="saved-creation-tooltip__prompt">{{ savedVideo.metadata?.prompt || 'Generated video' }}</div>
                <div v-if="creationIsOnDisplaySdCard(savedVideo, 'video')" class="text-caption mt-1"><v-icon size="14">mdi-sd</v-icon> {{ creationSdCardLabel(savedVideo, 'video') }}</div>
                <div v-if="formatGenerationTime(savedVideo.metadata?.generation_time_seconds)" class="text-caption mt-1">Generated in {{ formatGenerationTime(savedVideo.metadata?.generation_time_seconds) }}</div>
              </div>
            </v-tooltip>
            </div>
          </section>
        </template>
        <v-list v-if="!savedImagesLoading && filteredSavedVideos.length && imageLibraryView === 'list'" class="saved-image-library saved-image-list mt-6" density="compact" lines="two">
          <v-list-item v-for="savedVideo in filteredSavedVideos" :key="savedVideo.id" prepend-icon="mdi-movie-open-outline" @click="openSavedVideo(savedVideo)" @contextmenu="openSavedVideoContextMenu($event, savedVideo)">
            <v-list-item-title>{{ savedVideo.metadata?.prompt || 'Generated video' }}</v-list-item-title>
            <template #append>
              <v-chip v-if="creationIsOnDisplaySdCard(savedVideo, 'video')" size="x-small" color="success" variant="tonal" prepend-icon="mdi-sd" class="mr-1">On SD card</v-chip>
              <v-btn icon="mdi-dots-vertical" size="small" variant="text" aria-label="More actions for saved video" title="More actions" @pointerdown.stop @click.stop="openSavedVideoActions($event, savedVideo)" />
            </template>
            <v-list-item-subtitle>{{ savedVideo.metadata?.model?.name || 'LTX-Video' }} · {{ new Date(savedVideo.created_at).toLocaleString() }}</v-list-item-subtitle>
          </v-list-item>
        </v-list>
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
        <v-list-item prepend-icon="mdi-text" title="Use prompt" @click="useSavedImageSettings(contextMenuSavedImage?.metadata, 'prompt')" />
        <v-list-item prepend-icon="mdi-dice-5" title="Use seed" @click="useSavedImageSettings(contextMenuSavedImage?.metadata, 'seed')" />
        <v-list-item prepend-icon="mdi-foot-print" title="Use steps" @click="useSavedImageSettings(contextMenuSavedImage?.metadata, 'steps')" />
        <v-list-item prepend-icon="mdi-brain" title="Use model" @click="useSavedImageSettings(contextMenuSavedImage?.metadata, 'model')" />
        <v-list-item prepend-icon="mdi-rotate-right" title="Use rotation" @click="useSavedImageSettings(contextMenuSavedImage?.metadata, 'rotation')" />
        <v-divider class="my-1" />
        <v-list-item color="primary" prepend-icon="mdi-restore" title="Use all" @click="useSavedImageSettings(contextMenuSavedImage?.metadata, 'all')" />
        <v-list-item color="primary" prepend-icon="mdi-monitor-dashboard" :title="showOnDisplayLabel" :disabled="!hasDisplayTargets || showingSavedImageOnDisplay" @click="showSavedImageOnDisplay(contextMenuSavedImage)" />
        <v-list-item
          color="primary"
          :prepend-icon="creationIsSavedForCurrentDisplay(contextMenuSavedImage, 'image') ? 'mdi-check-circle' : 'mdi-sd'"
          :title="creationIsSavedForCurrentDisplay(contextMenuSavedImage, 'image') ? alreadySavedToDisplaySdCardLabel : saveToDisplaySdCardLabel"
          :disabled="!activeDisplayOnline || savingToDisplaySdCard || creationIsSavedForCurrentDisplay(contextMenuSavedImage, 'image')"
          @click="saveContextMenuImageToDisplaySdCard"
        />
        <v-list-item color="primary" prepend-icon="mdi-movie-open-plus" title="Animate as video" :disabled="health?.device !== 'cuda'" @click="animateSavedImage(contextMenuSavedImage)" />
        <v-divider class="my-1" />
        <v-list-item color="error" prepend-icon="mdi-delete-outline" title="Delete from Creation Library" @click="confirmDeleteSavedImage" />
      </v-list>
    </v-menu>

    <v-menu v-model="savedVideoContextMenu" :target="savedVideoContextMenuPosition" location="bottom start" :close-on-content-click="true">
      <v-list min-width="230" density="comfortable">
        <v-list-subheader>Reuse video settings</v-list-subheader>
        <v-list-item prepend-icon="mdi-text" title="Use prompt" @click="useSavedVideoSettings(contextMenuSavedVideo?.metadata, 'prompt')" />
        <v-list-item prepend-icon="mdi-dice-5" title="Use seed" @click="useSavedVideoSettings(contextMenuSavedVideo?.metadata, 'seed')" />
        <v-list-item prepend-icon="mdi-foot-print" title="Use steps" @click="useSavedVideoSettings(contextMenuSavedVideo?.metadata, 'steps')" />
        <v-list-item prepend-icon="mdi-brain" title="Use model" @click="useSavedVideoSettings(contextMenuSavedVideo?.metadata, 'model')" />
        <v-list-item prepend-icon="mdi-filmstrip" title="Use length" @click="useSavedVideoSettings(contextMenuSavedVideo?.metadata, 'frames')" />
        <v-list-item prepend-icon="mdi-speedometer" title="Use frame rate" @click="useSavedVideoSettings(contextMenuSavedVideo?.metadata, 'fps')" />
        <v-divider class="my-1" />
        <v-list-item color="primary" prepend-icon="mdi-restore" title="Use all" @click="useSavedVideoSettings(contextMenuSavedVideo?.metadata, 'all')" />
        <v-list-item color="primary" prepend-icon="mdi-play-circle-outline" :title="showOnDisplayLabel" :disabled="!activeDisplayOnline || showingVideoOnDisplay" @click="showSavedVideoOnDisplay(contextMenuSavedVideo?.id)" />
        <v-list-item
          color="primary"
          :prepend-icon="creationIsSavedForCurrentDisplay(contextMenuSavedVideo, 'video') ? 'mdi-check-circle' : 'mdi-sd'"
          :title="creationIsSavedForCurrentDisplay(contextMenuSavedVideo, 'video') ? alreadySavedToDisplaySdCardLabel : saveToDisplaySdCardLabel"
          :disabled="!activeDisplayOnline || savingVideoToDisplaySdCard || creationIsSavedForCurrentDisplay(contextMenuSavedVideo, 'video')"
          @click="saveSavedVideoToDisplaySdCard"
        />
        <v-list-item prepend-icon="mdi-download" title="Download MP4" :href="contextMenuSavedVideo ? `/saved-videos/${encodeURIComponent(contextMenuSavedVideo.id)}/video` : undefined" />
        <v-divider class="my-1" />
        <v-list-item color="error" prepend-icon="mdi-delete-outline" title="Delete from Creation Gallery" @click="confirmDeleteSavedVideo" />
      </v-list>
    </v-menu>

    <v-dialog v-model="deleteSavedImageDialog" max-width="440" width="calc(100% - 32px)">
      <v-card title="Delete saved image">
        <v-card-text>
          Remove this image from the Creation Library? This cannot be undone.
          <v-checkbox v-model="deleteSavedImageDontAskAgain" label="Don't ask again" density="compact" hide-details class="mt-3" />
        </v-card-text>
        <v-card-actions class="px-6 pb-5">
          <v-spacer />
          <v-btn variant="text" :disabled="deletingSavedImage" @click="deleteSavedImageDialog = false">Keep image</v-btn>
          <v-btn color="error" variant="flat" :loading="deletingSavedImage" @click="deleteSavedImage">Delete image</v-btn>
        </v-card-actions>
      </v-card>
    </v-dialog>

    <v-dialog v-model="deleteSavedVideoDialog" max-width="440" width="calc(100% - 32px)">
      <v-card title="Delete saved video">
        <v-card-text>
          Remove this video from the Creation Gallery? This cannot be undone.
          <v-checkbox v-model="deleteSavedVideoDontAskAgain" label="Don't ask again" density="compact" hide-details class="mt-3" />
        </v-card-text>
        <v-card-actions class="px-6 pb-5">
          <v-spacer />
          <v-btn variant="text" :disabled="deletingSavedVideo" @click="deleteSavedVideoDialog = false">Keep video</v-btn>
          <v-btn color="error" variant="flat" :loading="deletingSavedVideo" @click="deleteSavedVideo">Delete video</v-btn>
        </v-card-actions>
      </v-card>
    </v-dialog>

    <v-dialog v-model="deleteSdCardFileDialog" max-width="440" width="calc(100% - 32px)">
      <v-card :title="`Delete SD card ${displaySdCardMediaType(sdCardFileToDelete)}`">
        <v-card-text>
          Remove this <strong>{{ displaySdCardMediaType(sdCardFileToDelete) }}</strong> from the display SD card?
          <div class="font-weight-medium text-break mt-3">{{ sdCardFileToDelete?.name }}</div>
          <div class="text-body-2 text-medium-emphasis mt-2">This cannot be undone.</div>
          <v-checkbox v-model="deleteSdCardFileDontAskAgain" label="Don't ask again" density="compact" hide-details class="mt-3" />
        </v-card-text>
        <v-card-actions class="px-6 pb-5">
          <v-spacer />
          <v-btn variant="text" :disabled="deletingSdCardFile" @click="deleteSdCardFileDialog = false">Keep file</v-btn>
          <v-btn color="error" variant="flat" :loading="deletingSdCardFile" @click="deleteDisplaySdCardFile">Delete {{ displaySdCardMediaType(sdCardFileToDelete) }}</v-btn>
        </v-card-actions>
      </v-card>
    </v-dialog>

    <v-dialog v-model="deleteSdCardFilesDialog" max-width="480" width="calc(100% - 32px)">
      <v-card :title="`Delete ${sdCardFilesToDelete.length} SD card ${sdCardFilesToDelete.length === 1 ? 'file' : 'files'}`">
        <v-card-text>
          Remove these {{ sdCardFilesToDelete.length }} files from the display SD card? This cannot be undone.
          <v-list density="compact" class="mt-3 border rounded">
            <v-list-item v-for="file in sdCardFilesToDelete.slice(0, 5)" :key="file.name" :title="file.name" />
            <v-list-item v-if="sdCardFilesToDelete.length > 5" :title="`…and ${sdCardFilesToDelete.length - 5} more`" />
          </v-list>
          <v-checkbox v-model="deleteSdCardFilesDontAskAgain" label="Don't ask again" density="compact" hide-details class="mt-3" />
        </v-card-text>
        <v-card-actions class="px-6 pb-5">
          <v-spacer />
          <v-btn variant="text" :disabled="deletingSdCardFiles" @click="deleteSdCardFilesDialog = false">Keep files</v-btn>
          <v-btn color="error" variant="flat" :loading="deletingSdCardFiles" @click="deleteSelectedDisplaySdCardFiles">Delete {{ sdCardFilesToDelete.length }} {{ sdCardFilesToDelete.length === 1 ? 'file' : 'files' }}</v-btn>
        </v-card-actions>
      </v-card>
    </v-dialog>

    <v-dialog v-model="removeVideoModelDialog" max-width="480" width="calc(100% - 32px)">
      <v-card title="Remove video model">
        <v-card-text>
          Remove <strong>{{ videoModelToRemove?.name }}</strong> from this computer? It can be downloaded again when needed.
          <div v-if="videoModelToRemove?.removal_note" class="text-body-2 text-medium-emphasis mt-3">{{ videoModelToRemove.removal_note }}</div>
        </v-card-text>
        <v-card-actions class="px-6 pb-5">
          <v-spacer />
          <v-btn variant="text" :disabled="Boolean(removingVideoModelId)" @click="removeVideoModelDialog = false">Keep model</v-btn>
          <v-btn color="error" variant="flat" :loading="Boolean(removingVideoModelId)" @click="removeVideoModel">Remove model</v-btn>
        </v-card-actions>
      </v-card>
    </v-dialog>

    <v-dialog v-model="removeImageModelDialog" max-width="480" width="calc(100% - 32px)">
      <v-card title="Remove image model">
        <v-card-text>
          Remove <strong>{{ imageModelToRemove?.name }}</strong> from this computer? It can be downloaded again when needed.
          <div v-if="imageModelToRemove?.active" class="text-body-2 text-medium-emphasis mt-3">This is the selected model. It will be unloaded and downloaded again the next time you generate an image.</div>
        </v-card-text>
        <v-card-actions class="px-6 pb-5">
          <v-spacer />
          <v-btn variant="text" :disabled="Boolean(removingImageModelId)" @click="removeImageModelDialog = false">Keep model</v-btn>
          <v-btn color="error" variant="flat" :loading="Boolean(removingImageModelId)" @click="removeImageModel">Remove model</v-btn>
        </v-card-actions>
      </v-card>
    </v-dialog>

    <v-dialog v-model="mobileAccessDialog" max-width="480" width="calc(100% - 32px)">
      <v-card title="Use ESPImageServer from your phone">
        <v-card-text>
          <div class="text-body-2 text-medium-emphasis">Scan this code with your phone camera while it is on the same Wi-Fi network.</div>
          <div class="d-flex justify-center my-5">
            <v-progress-circular v-if="mobileAccessQrCodeLoading" indeterminate color="primary" size="72" />
            <v-img v-else-if="mobileAccessQrCode" :src="mobileAccessQrCode" width="224" max-width="100%" aspect-ratio="1" alt="QR code for opening ESPImageServer on a phone" />
          </div>
          <v-text-field :model-value="mobileAccessUrl" label="Phone address" readonly variant="outlined" density="comfortable" hide-details class="mb-4">
            <template #append-inner>
              <v-btn icon="mdi-content-copy" size="small" variant="text" aria-label="Copy phone address" title="Copy phone address" @click="copyMobileAccessUrl(mobileAccessUrl, 'Phone')" />
            </template>
          </v-text-field>
          <v-text-field v-if="mobileAccessFallbackUrl" :model-value="mobileAccessFallbackUrl" label="Fallback address" readonly variant="outlined" density="comfortable" hide-details class="mb-4">
            <template #append-inner>
              <v-btn icon="mdi-content-copy" size="small" variant="text" aria-label="Copy fallback address" title="Copy fallback address" @click="copyMobileAccessUrl(mobileAccessFallbackUrl, 'Fallback')" />
            </template>
          </v-text-field>
          <v-alert v-if="mobileAccessFallbackUrl" type="info" variant="tonal" density="compact">
            If the phone address does not open, use the fallback address. It can change when your computer reconnects to Wi-Fi.
          </v-alert>
          <v-alert v-else type="warning" variant="tonal" density="compact">
            A numeric fallback address is unavailable. Check that this computer is connected to your local network.
          </v-alert>
          <v-alert v-if="mobileAccessCopyStatus" :type="mobileAccessCopyStatus.startsWith('Could not') ? 'warning' : 'success'" variant="tonal" density="compact" class="mt-4">
            {{ mobileAccessCopyStatus }}
          </v-alert>
        </v-card-text>
        <v-card-actions class="px-6 pb-5">
          <v-spacer />
          <v-btn variant="text" @click="mobileAccessDialog = false">Close</v-btn>
        </v-card-actions>
      </v-card>
    </v-dialog>

    <v-main class="app-shell">
      <v-container class="app-container py-4 py-sm-7">
        <v-alert v-if="!compact && !mobileAccessPromptDismissed" type="info" variant="tonal" icon="mdi-cellphone-link" class="mb-4">
          <div class="font-weight-medium">Use ESPImageServer from your phone</div>
          <div class="text-body-2 mt-1">Control generation and your display from another device on the same Wi-Fi network.</div>
          <template #append>
            <div class="d-flex flex-wrap ga-2 justify-end">
              <v-btn size="small" color="primary" variant="flat" @click="openMobileAccessDialog(true)">Show QR code</v-btn>
              <v-btn size="small" variant="text" @click="dismissMobileAccessPrompt">Not now</v-btn>
            </div>
          </template>
        </v-alert>
        <v-card v-if="page === 'queue'" class="mx-auto" max-width="960">
          <v-card-title class="page-card-title d-flex align-center text-h6">
            <div class="page-card-title__heading d-flex align-center">
              <v-icon class="mr-2">mdi-format-list-numbered</v-icon><span>Generation queue</span>
            </div>
            <v-spacer />
            <div class="page-card-title__actions d-flex align-center flex-wrap ga-2">
              <v-chip size="small" variant="tonal">{{ activeGenerationQueue.length }} active</v-chip>
              <v-btn v-if="finishedGenerationQueue.length" size="small" variant="text" color="error" prepend-icon="mdi-delete-sweep-outline" @click="clearFinishedGenerationQueue">Clear finished</v-btn>
            </div>
          </v-card-title>
          <v-list v-if="activeGenerationQueue.length" density="comfortable" lines="two">
            <v-list-item v-for="job in activeGenerationQueue" :key="job.id">
              <template #prepend>
                <v-avatar rounded="sm" size="56" class="queue-job-thumbnail">
                  <v-icon :icon="job.kind === 'video' ? 'mdi-movie-open-outline' : 'mdi-image-outline'" />
                </v-avatar>
              </template>
              <v-list-item-title>{{ job.kind === 'video' ? 'Video' : 'Image' }} · {{ job.metadata?.label || 'Generation request' }}</v-list-item-title>
              <v-list-item-subtitle>{{ job.status === 'queued' ? `Waiting · position ${job.queue_position}` : job.stage }}<span v-if="job.status !== 'queued' && job.progress"> · {{ job.progress }}%</span></v-list-item-subtitle>
              <template #append><v-btn icon="mdi-cancel" variant="text" color="warning" size="small" :loading="cancellingQueueJobId === job.id" :disabled="!job.cancellable || Boolean(cancellingQueueJobId)" :aria-label="`Cancel ${job.kind} job`" :title="`Cancel ${job.kind} job`" @click="cancelQueuedGeneration(job)" /></template>
              <v-progress-linear v-if="job.status !== 'queued'" class="mt-2" :model-value="job.progress" color="primary" height="6" rounded />
            </v-list-item>
          </v-list>
          <v-card-text v-if="!activeGenerationQueue.length" class="text-medium-emphasis py-6 text-center">No image or video jobs are waiting.</v-card-text>
          <template v-if="finishedGenerationQueue.length">
            <v-divider />
            <div class="px-4 pt-4 text-overline text-medium-emphasis">Recent jobs</div>
            <v-list density="comfortable" lines="two">
              <v-list-item v-for="job in finishedGenerationQueue" :key="job.id">
                <template #prepend>
                  <v-avatar v-if="job.status === 'complete'" rounded="sm" size="56" class="queue-job-thumbnail">
                    <v-img v-if="job.kind === 'image'" :src="`/generation-jobs/${encodeURIComponent(job.id)}/image`" cover />
                    <video v-else :src="`/video-generation-jobs/${encodeURIComponent(job.id)}/video`" muted preload="metadata" />
                  </v-avatar>
                  <v-icon v-else :color="job.status === 'failed' ? 'error' : 'warning'" :icon="job.status === 'failed' ? 'mdi-alert-circle' : 'mdi-cancel'" />
                </template>
                <v-list-item-title>{{ job.kind === 'video' ? 'Video' : 'Image' }} · {{ job.metadata?.label || 'Generation request' }}</v-list-item-title>
                <v-list-item-subtitle>{{ job.status === 'complete' ? `${job.kind === 'video' ? 'Video' : 'Image'} generation complete${formatGenerationTime(job.generation_time_seconds) ? ` · Generated in ${formatGenerationTime(job.generation_time_seconds)}` : ''}` : job.error || job.stage }}</v-list-item-subtitle>
                <template #append>
                  <v-btn v-if="job.status === 'complete'" icon="mdi-open-in-new" size="small" variant="text" :aria-label="`Open completed ${job.kind}`" :title="`Open completed ${job.kind}`" @click="openQueuedGeneration(job)" />
                  <v-chip :color="job.status === 'complete' ? 'success' : job.status === 'failed' ? 'error' : 'warning'" size="small" variant="tonal">{{ job.status === 'complete' ? 'Complete' : job.status === 'failed' ? 'Failed' : 'Cancelled' }}</v-chip>
                </template>
              </v-list-item>
            </v-list>
          </template>
        </v-card>
        <v-card v-if="page === 'diagnostics'" class="mx-auto" max-width="960">
          <v-card-title class="page-card-title d-flex align-center text-h6">
            <div class="page-card-title__heading d-flex align-center">
              <v-icon class="mr-2" icon="mdi-text-box-outline" /><span>Diagnostics</span>
            </div>
            <v-spacer />
            <div class="page-card-title__actions d-flex align-center flex-wrap ga-2">
              <template v-if="diagnosticsTab === 'summary'">
                <v-btn size="small" variant="text" prepend-icon="mdi-content-copy" @click="copyDiagnostics">Copy diagnostics</v-btn>
                <v-btn size="small" variant="text" color="error" prepend-icon="mdi-delete-outline" @click="clearDiagnostics">Clear</v-btn>
              </template>
              <template v-else>
                <v-btn size="small" variant="text" prepend-icon="mdi-content-copy" @click="copyConsoleOutput">Copy console</v-btn>
                <v-btn size="small" variant="text" color="error" prepend-icon="mdi-delete-outline" @click="clearConsoleOutput">Clear console</v-btn>
              </template>
            </div>
          </v-card-title>
          <v-tabs v-model="diagnosticsTab" color="primary">
            <v-tab value="summary" prepend-icon="mdi-clipboard-text-outline">Summary</v-tab>
            <v-tab value="console" prepend-icon="mdi-console-line">Console</v-tab>
          </v-tabs>
          <v-divider />
          <v-window v-model="diagnosticsTab">
            <v-window-item value="summary">
          <v-list v-if="diagnostics.length" density="comfortable" lines="two">
            <v-list-item v-for="entry in diagnostics" :key="`${entry.timestamp}-${entry.message}`" :class="entry.level === 'error' ? 'text-error' : ''">
              <v-list-item-title>{{ entry.message }}</v-list-item-title>
              <v-list-item-subtitle>{{ new Date(entry.timestamp).toLocaleTimeString() }} · {{ entry.source }}</v-list-item-subtitle>
            </v-list-item>
          </v-list>
          <v-card-text v-else class="text-medium-emphasis py-8 text-center">No diagnostic events yet.</v-card-text>
            </v-window-item>
            <v-window-item value="console">
              <v-card-text>
                <div class="d-flex align-center ga-2 mb-3">
                  <v-text-field v-model="consoleSearch" density="compact" variant="outlined" hide-details clearable prepend-inner-icon="mdi-magnify" label="Filter console output" />
                  <v-btn icon="mdi-chevron-down" size="small" variant="text" aria-label="Scroll console to newest output" title="Scroll to newest output" @click="scrollConsoleToBottom" />
                </div>
                <div ref="consoleOutputElement" class="console-output" @scroll="updateConsoleAutoScroll">
                  <pre v-if="filteredConsoleOutput.length">{{ filteredConsoleOutput.join('\n') }}</pre>
                  <div v-else class="text-medium-emphasis text-center pa-8">{{ consoleOutput.length ? 'No console lines match this filter.' : 'No console output has been recorded yet.' }}</div>
                </div>
                <div class="d-flex flex-wrap justify-space-between ga-2 mt-3 text-caption text-medium-emphasis">
                  <span>{{ filteredConsoleOutput.length }} of {{ consoleOutput.length }} recent log entries</span>
                  <span>Live output refreshes every second while this tab is active. Secrets are redacted.</span>
                </div>
              </v-card-text>
            </v-window-item>
          </v-window>
        </v-card>
        <template v-if="page === 'generate'">
        <v-row>
        <v-col cols="12" lg="5">
        <v-card class="generation-card">
          <v-card-text>
            <v-alert v-if="videoGenerationActive" type="info" variant="tonal" density="compact" class="compact-stack-alert-actions mb-4">
              Video generation is using the graphics card. You can add an image to the queue; it will start when the video finishes.
              <template #append><v-btn size="small" variant="text" @click="page = 'queue'">View queue</v-btn></template>
            </v-alert>
            <v-form @submit.prevent="generate">
              <v-select
                :model-value="activeModelId"
                :items="modelOptions"
                label="Image model"
                variant="outlined"
                density="comfortable"
                :disabled="models.length === 0"
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
              <v-alert :type="display?.connected && activeDisplayOnline ? 'info' : 'warning'" variant="tonal" density="compact" class="mb-4" :prepend-icon="activeDisplayOnline ? 'mdi-monitor-check' : 'mdi-monitor-off'">
                <template v-if="display?.connected && activeDisplayOnline">
                  Images will be sent to <strong>{{ display.name }}</strong> ({{ display.width }} × {{ display.height }}). Choose a different active display from the app bar.
                </template>
                <template v-else-if="display?.connected">
                  <strong>{{ display.name }} is offline.</strong> You can still generate an image for this screen. When it reconnects, it will request the most recently generated image for {{ display.name }}.
                </template>
                <template v-else>
                  Turn on an ESP32 display, then choose it from the Active display menu in the app bar.
                </template>
              </v-alert>
              <v-select
                :model-value="displayRotation"
                :items="rotationOptions"
                :label="display?.connected ? `Image rotation for ${display.name}` : 'Image rotation'"
                variant="outlined"
                density="comfortable"
                :disabled="generationBusy || Boolean(displays.length && !display?.connected)"
                :hint="display?.connected ? activeDisplayOnline ? 'Applied by ESPImageServer before the JPEG is sent. Your ESP32 firmware does not need to change.' : 'Saved by ESPImageServer and used when this display next receives an image.' : 'Choose one display to change its rotation.'"
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
              <v-textarea
                v-if="models.find(model => model.id === activeModelId)?.supports_negative_prompt"
                v-model="negativePrompt"
                label="What should the image avoid? (optional)"
                hint="For example: blurry, distorted, extra fingers, text"
                persistent-hint
                maxlength="1000"
                counter="1000"
                variant="outlined"
                rows="2"
                auto-grow
                class="mb-2"
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
              <div class="generation-form-actions">
                <v-btn type="submit" color="primary" :disabled="models.length === 0 || Boolean(displays.length && !hasDisplayTargets)" prepend-icon="mdi-image-plus">
                  {{ generationBusy ? 'Add image to queue' : 'Generate image' }}
                </v-btn>
                <v-btn v-if="generating" color="warning" variant="tonal" :loading="cancelling" :disabled="cancelling" prepend-icon="mdi-cancel" @click="cancelGeneration">
                  {{ activeJobId ? 'Cancel generation' : 'Cancel' }}
                </v-btn>
              </div>
              <div v-if="generating && activeImageJobRunning" class="mt-5">
                <div class="d-flex justify-space-between text-body-2 mb-2">
                  <span>{{ generationStage }}</span><span>{{ activeJobId || generationProgress ? `${generationProgress}%` : 'Preparing' }}</span>
                </div>
                <v-progress-linear :model-value="generationProgress" :indeterminate="!activeJobId && !generationProgress" color="primary" height="10" rounded />
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
          <v-card-title class="d-flex flex-wrap align-center ga-2 text-subtitle-1">
            <span>{{ selectedSavedImage ? 'Selected saved image' : 'Latest completed image' }}</span>
            <v-chip v-if="activeImageQueueJob" color="primary" size="small" variant="tonal" prepend-icon="mdi-image-outline" :title="activeImageQueueJob.stage">
              {{ resultPanelQueueStatus(activeImageQueueJob) }}
            </v-chip>
          </v-card-title>
          <v-alert :type="display?.connected ? 'info' : 'warning'" variant="tonal" density="compact" class="display-context-bar mx-4 mb-3" :prepend-icon="activeDisplayOnline ? 'mdi-monitor-check' : 'mdi-monitor-off'">
            <strong>Working with:</strong> {{ displayManagementLabel }}
            <div class="text-caption mt-1">New display and SD-card actions use this active display.</div>
          </v-alert>
          <v-card-subtitle v-if="activeImageQueueJob && imageUrl" class="pb-3">The previous image remains available until this job is complete.</v-card-subtitle>
          <v-card-subtitle v-else-if="selectedSavedImage" class="pb-3">Previewing a saved image. Use its settings or show it on the display when you are ready.</v-card-subtitle>
          <v-progress-linear
            v-if="activeImageQueueJob"
            class="mx-4 mb-3"
            :color="activeImageQueueJob.status === 'cancelling' ? 'warning' : 'primary'"
            :indeterminate="activeImageQueueJob.status !== 'running'"
            :model-value="activeImageQueueJob.status === 'running' ? activeImageQueueJob.progress : undefined"
            height="6"
            rounded
          />
          <v-img v-if="previewUrl" :src="previewUrl" alt="Image fitted to the connected ESP32 display" />
          <v-sheet v-else class="preview-placeholder d-flex flex-column align-center justify-center text-center pa-8">
            <div class="display-preview-stage mb-4">
              <div class="display-preview-device" :style="imageDisplayPreviewStyle" :aria-label="`Selected display preview: ${imageDisplayPreviewSizeLabel}, ${imageDisplayPreviewRotationLabel}`">
                <div class="display-preview-device__artwork">
                  <v-icon size="32">mdi-image-outline</v-icon>
                </div>
              </div>
            </div>
            <div class="text-h6">Your generated image will appear here</div>
            <div class="text-body-2 text-medium-emphasis mt-2">{{ imageDisplayPreviewSizeLabel }} · {{ imageDisplayPreviewRotationLabel }}</div>
            <div class="text-body-2 text-medium-emphasis mt-1">
              Describe an image, choose your settings, then select Generate image.
            </div>
          </v-sheet>
          <v-card-actions v-if="imageUrl" class="result-actions">
            <v-chip v-if="previewFittedFor" size="small" variant="tonal" prepend-icon="mdi-monitor-dashboard">
              Preview: fitted for {{ previewFittedFor.name }} ({{ previewFittedFor.width }}×{{ previewFittedFor.height }})
            </v-chip>
            <v-btn v-if="selectedSavedImage" color="primary" prepend-icon="mdi-restore" @click="useSelectedSavedImageSettings">
              Use saved settings
            </v-btn>
            <v-btn v-if="selectedSavedImage" color="primary" variant="tonal" prepend-icon="mdi-monitor-dashboard" :loading="showingSavedImageOnDisplay" :disabled="!hasDisplayTargets" @click="showSavedImageOnDisplay()">
              {{ showOnDisplayLabel }}
            </v-btn>
            <v-btn :href="imageUrl" download="esp-image.jpg" color="secondary" prepend-icon="mdi-download">
              Download JPEG
            </v-btn>
            <v-btn color="primary" variant="tonal" prepend-icon="mdi-sd" :loading="savingToDisplaySdCard" :disabled="!activeDisplayOnline" @click="saveImageToDisplaySdCard(selectedSavedImage)">
              {{ saveToDisplaySdCardLabel }}
            </v-btn>
            <v-btn variant="text" prepend-icon="mdi-image-text" @click="openMetadataPane">Creation Library</v-btn>
          </v-card-actions>
          <v-alert v-if="imageUrl && !autoSaveImages" type="warning" variant="tonal" class="compact-stack-alert-actions mx-4 mb-4" density="comfortable" icon="mdi-content-save-alert">
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

        <v-card v-if="page === 'video'" class="mx-auto" max-width="1400">
          <v-card-title class="text-h5 pt-5">Generate video</v-card-title>
          <v-card-text>
            <v-alert v-if="health?.device !== 'cuda'" type="error" variant="tonal" density="compact" class="mb-4" icon="mdi-cpu-64-bit">
              Video generation cannot run in CPU mode. Re-run the installer and choose <strong>NVIDIA CUDA acceleration</strong>, then restart ESPImageServer.
            </v-alert>
            <v-alert v-if="imageGenerationActive" type="info" variant="tonal" density="compact" class="compact-stack-alert-actions mb-4">
              Image generation is using the graphics card. You can add a video to the queue; it will start when the image finishes.
              <template #append><v-btn size="small" variant="text" @click="page = 'queue'">View queue</v-btn></template>
            </v-alert>
            <v-row>
              <v-col cols="12" lg="5">
            <v-form @submit.prevent="generateVideo">
              <v-alert v-if="display?.connected && !activeDisplayOnline" type="warning" variant="tonal" density="compact" class="mb-3" prepend-icon="mdi-monitor-off">
                <strong>{{ display.name }} is offline.</strong> This video will still be created for its {{ display.width }} × {{ display.height }} screen, but display and SD-card actions are unavailable until it reconnects.
              </v-alert>
              <div v-if="display?.connected && activeDisplayOnline" class="text-caption text-medium-emphasis mb-3">Video will be created at your connected display’s native size: {{ display.width }} × {{ display.height }}.</div>
              <v-select
                :model-value="videoRotation"
                :items="rotationOptions"
                :label="display?.connected ? `Video rotation for ${display.name}` : 'Video rotation'"
                variant="outlined"
                density="comfortable"
                :disabled="generationBusy || Boolean(displays.length && !display?.connected)"
                hint="This setting applies only to generated videos. The video is generated in the rotated aspect, then delivered at the screen’s native dimensions."
                persistent-hint
                class="mb-4"
                @update:model-value="setVideoRotation"
              />
              <v-alert v-if="videoModelId === 'wan-2.1-t2v-1.3b'" type="info" variant="tonal" density="compact" class="mb-4">
                Wan 2.1 uses text only. It generates at a larger 480p-class working size, then is resized for your display. The first download can take several minutes.
              </v-alert>
              <v-alert v-else-if="videoModelId === 'hunyuanvideo-1.5-480p'" type="info" variant="tonal" density="compact" class="mb-4">
                HunyuanVideo 1.5 can create a video from text or animate a selected Creation Gallery image. It uses a 480p-class working size, then is resized for your display. Its first download can take several minutes.
              </v-alert>
              <v-alert v-if="videoSourceImage" type="success" variant="tonal" density="compact" class="mb-4">
                <div class="d-flex align-center">
                      <v-avatar rounded size="72" class="mr-4"><v-img :src="`/saved-images/${encodeURIComponent(videoSourceImage.id)}/thumbnail`" /></v-avatar>
                  <span>Animating the selected Creation Gallery image as the first frame.</span>
                  <v-spacer /><v-btn icon="mdi-close" size="small" variant="text" aria-label="Stop using this image for the video" title="Stop using this image" @click="videoSourceImage = null" />
                </div>
              </v-alert>
              <v-select v-model="videoModelId" :items="videoModels" label="Video model" variant="outlined" density="comfortable" class="mb-3" />
              <v-card variant="tonal" color="primary" class="mb-4">
                <v-card-title class="text-subtitle-1">Which video model should I use?</v-card-title>
                <v-card-text class="pt-0">
                  <div class="font-weight-medium">{{ selectedVideoModel.title }}</div>
                  <div class="text-body-2 mt-1">{{ selectedVideoModel.description }}</div>
                </v-card-text>
              </v-card>
              <v-switch
                :model-value="autoSaveVideos"
                label="Save generated videos automatically"
                color="primary"
                :loading="autoSaveVideoSaving"
                :disabled="generationBusy || autoSaveVideoSaving"
                hint="When off, use Save to Creation Gallery after a video finishes."
                persistent-hint
                class="mb-4"
                @update:model-value="setAutoSaveVideos"
              />
              <v-textarea v-model="videoPrompt" label="Describe the video" hint="For best results, specify the subject, setting, lighting, camera shot, and one simple movement." persistent-hint maxlength="1000" counter="1000" required variant="outlined" rows="4" auto-grow class="mb-4" />
              <v-row dense class="mt-1">
                <v-col cols="12" sm="6"><v-select v-model="videoFps" label="Frames per second" variant="outlined" density="comfortable" :items="[8, 12, 15, 24]" /></v-col>
                <v-col cols="12">
                  <div class="text-subtitle-2 mb-2">Video duration</div>
                  <div class="d-flex flex-wrap ga-2">
                    <v-btn
                      v-for="preset in videoDurationPresets"
                      :key="preset.seconds"
                      type="button"
                      size="small"
                      :color="videoDurationPresetSeconds === preset.seconds ? 'primary' : undefined"
                      :variant="videoDurationPresetSeconds === preset.seconds ? 'flat' : 'tonal'"
                      :disabled="!isVideoDurationAvailable(preset.seconds)"
                      :title="isVideoDurationAvailable(preset.seconds) ? `Select about ${preset.title}` : `Unavailable at ${videoFps} fps; the 249-frame limit allows up to ${(249 / Number(videoFps)).toFixed(1)} seconds.`"
                      @click="selectVideoDuration(preset.seconds)"
                    >
                      {{ preset.title }}
                    </v-btn>
                  </div>
                  <div class="text-caption text-medium-emphasis mt-2">Selected: {{ videoDurationLabel }} at {{ videoFps }} fps ({{ videoFrames }} frames).</div>
                </v-col>
                <v-col cols="12">
                  <v-btn type="button" size="small" variant="text" prepend-icon="mdi-tune-variant" @click="showAdvancedVideoFrames = !showAdvancedVideoFrames">
                    {{ showAdvancedVideoFrames ? 'Hide advanced frame count' : 'Advanced: choose frame count' }}
                  </v-btn>
                  <v-text-field v-if="showAdvancedVideoFrames" v-model.number="videoFrames" label="Frames" type="number" min="9" max="249" step="8" variant="outlined" density="comfortable" hint="Valid values run from 9 to 249 in steps of 8." persistent-hint class="mt-2" />
                </v-col>
                <v-col cols="12" sm="6"><v-select v-model="videoSteps" label="Generation steps" variant="outlined" density="comfortable" :hint="videoModelId === 'wan-2.1-t2v-1.3b' ? '30 is a good starting point for Wan 2.1.' : videoModelId === 'hunyuanvideo-1.5-480p' ? '30 is recommended for HunyuanVideo 1.5.' : videoModelId === 'ltx-2b-0.9.6-dev' ? '30 is recommended for the quality model.' : '8 is recommended for the distilled model.'" persistent-hint :items="videoStepOptions" /></v-col>
                <v-col cols="12" sm="6"><v-text-field v-model="videoSeed" label="Seed" type="number" min="0" max="4294967295" variant="outlined" density="comfortable" append-inner-icon="mdi-dice-5" @click:append-inner="videoSeed = createRandomSeed()" /></v-col>
              </v-row>
              <div class="generation-form-actions mt-4">
                <v-btn type="submit" color="primary" :disabled="health?.device !== 'cuda'" prepend-icon="mdi-movie-open-plus">{{ generationBusy ? 'Add video to queue' : 'Generate video' }}</v-btn>
                <v-btn v-if="generatingVideo" color="warning" variant="tonal" :loading="cancellingVideo" @click="cancelVideoGeneration">Cancel</v-btn>
              </div>
            </v-form>
            <div v-if="generatingVideo && activeVideoJobRunning" class="mt-5">
              <div class="d-flex justify-space-between text-body-2 mb-2"><span>{{ videoStage }}</span><span>{{ videoProgress }}%</span></div>
              <v-progress-linear :model-value="videoProgress" :indeterminate="!activeVideoJobId" color="primary" height="10" rounded />
            </div>
            <v-alert v-else-if="videoStage" type="success" variant="tonal" density="compact" class="mt-4">{{ videoStage }}</v-alert>
            <v-alert v-if="videoError" type="error" variant="tonal" density="compact" class="mt-4">{{ videoError }}</v-alert>
              </v-col>
              <v-col cols="12" lg="7">
                <v-card class="generated-video-card h-100">
                  <v-card-title class="d-flex flex-wrap align-center ga-2 text-subtitle-1">
                    <span>Latest completed video</span>
                    <v-chip v-if="activeVideoQueueJob" color="primary" size="small" variant="tonal" prepend-icon="mdi-movie-open-outline" :title="activeVideoQueueJob.stage">
                      {{ resultPanelQueueStatus(activeVideoQueueJob) }}
                    </v-chip>
                  </v-card-title>
                  <v-alert :type="display?.connected ? 'info' : 'warning'" variant="tonal" density="compact" class="display-context-bar mx-4 mb-3" :prepend-icon="activeDisplayOnline ? 'mdi-monitor-check' : 'mdi-monitor-off'">
                    <strong>Working with:</strong> {{ displayManagementLabel }}
                    <div class="text-caption mt-1">New display and SD-card actions use this active display.</div>
                  </v-alert>
                  <v-card-subtitle v-if="activeVideoQueueJob && videoUrl" class="pb-3">The previous video remains available until this job is complete.</v-card-subtitle>
                  <v-progress-linear
                    v-if="activeVideoQueueJob"
                    class="mx-4 mb-3"
                    :color="activeVideoQueueJob.status === 'cancelling' ? 'warning' : 'primary'"
                    :indeterminate="activeVideoQueueJob.status !== 'running'"
                    :model-value="activeVideoQueueJob.status === 'running' ? activeVideoQueueJob.progress : undefined"
                    height="6"
                    rounded
                  />
                  <video v-if="videoUrl" :src="videoUrl" controls loop class="w-100 rounded" />
                  <v-sheet v-else class="preview-placeholder d-flex flex-column align-center justify-center text-center pa-8">
                    <div class="display-preview-stage mb-4">
                      <div class="display-preview-device" :style="videoDisplayPreviewStyle" :aria-label="`Selected display preview: ${videoDisplayPreviewSizeLabel}, ${videoDisplayPreviewRotationLabel}`">
                        <div class="display-preview-device__artwork">
                          <v-icon size="32">mdi-movie-open-outline</v-icon>
                        </div>
                      </div>
                    </div>
                    <div class="text-h6">Your generated video will appear here</div>
                    <div class="text-body-2 text-medium-emphasis mt-2">{{ videoDisplayPreviewSizeLabel }} · {{ videoDisplayPreviewRotationLabel }}</div>
                    <div class="text-body-2 text-medium-emphasis mt-1">Describe a scene, choose your settings, then select Generate video.</div>
                  </v-sheet>
                </v-card>
              </v-col>
            </v-row>
          </v-card-text>
          <v-card-actions v-if="videoUrl" class="result-actions">
            <v-btn :href="videoUrl" download="esp-image-video.mp4" color="secondary" prepend-icon="mdi-download">Download MP4</v-btn>
            <v-btn color="primary" variant="tonal" prepend-icon="mdi-bookmark-plus" :loading="savingVideoToCreationLibrary" :disabled="videoSavedToCreationLibrary" @click="saveVideoToCreationLibrary">
              {{ videoSavedToCreationLibrary ? 'Saved to Creation Gallery' : 'Save to Creation Gallery' }}
            </v-btn>
            <v-btn color="primary" prepend-icon="mdi-play-circle-outline" :loading="showingVideoOnDisplay" :disabled="!activeDisplayOnline || savingVideoToDisplaySdCard" @click="showSavedVideoOnDisplay">
              {{ showOnDisplayLabel }}
            </v-btn>
            <v-btn color="primary" variant="tonal" prepend-icon="mdi-sd" :loading="savingVideoToDisplaySdCard" :disabled="!activeDisplayOnline || savingVideoToDisplaySdCard" @click="saveCompletedVideoToDisplaySdCard">
              {{ saveToDisplaySdCardLabel }}
            </v-btn>
          </v-card-actions>
        </v-card>

        <v-card v-if="page === 'models'">
          <v-card-title class="text-h5 pt-5">Image models</v-card-title>
          <v-card-text class="text-body-1">
            Compare the available models. Choose the model to use from the Generate image page; it downloads once and stays on this computer.
          </v-card-text>
          <v-table v-if="!compact" class="model-table" hover density="comfortable">
            <thead>
              <tr>
                <th>Model</th>
                <th>Best for</th>
                <th>Hardware</th>
                <th>Status</th>
                <th class="text-right">Actions</th>
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
                      <a :href="model.model_card_url" target="_blank" rel="noopener noreferrer" class="text-caption text-primary">License &amp; usage <v-icon size="12">mdi-open-in-new</v-icon></a>
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
                <td class="text-right"><v-btn v-if="model.installed" color="error" variant="text" size="small" prepend-icon="mdi-delete-outline" :loading="removingImageModelId === model.id" :disabled="generationBusy" @click="confirmRemoveImageModel(model)">Remove</v-btn></td>
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
              <v-list-item-subtitle><a :href="model.model_card_url" target="_blank" rel="noopener noreferrer" class="text-primary">License &amp; usage <v-icon size="12">mdi-open-in-new</v-icon></a></v-list-item-subtitle>
              <v-list-item-subtitle>{{ model.speed }} · {{ model.hardware }}</v-list-item-subtitle>
              <template #append><div class="d-flex align-center"><v-chip v-if="model.active" color="success" variant="tonal" size="small">In use</v-chip><v-btn v-if="model.installed" color="error" icon="mdi-delete-outline" variant="text" size="small" :loading="removingImageModelId === model.id" :disabled="generationBusy" :aria-label="`Remove ${model.name}`" :title="`Remove ${model.name}`" @click="confirmRemoveImageModel(model)" /></div></template>
            </v-list-item>
          </v-list>
          <v-card-text class="text-caption text-medium-emphasis pt-3">
            NVIDIA models can still run without a compatible GPU, but generation may be impractically slow.
          </v-card-text>
          <v-divider class="mt-3" />
          <v-card-title class="text-h5 pt-5">Video models</v-card-title>
          <v-card-text class="text-body-1">
            Video models download the first time you use them. Remove downloaded models here to recover disk space; you can download them again later.
          </v-card-text>
          <v-table v-if="!compact" class="model-table" hover density="comfortable">
            <thead>
              <tr>
                <th>Model</th>
                <th>Best for</th>
                <th>Image animation</th>
                <th>Status</th>
                <th class="text-right">Actions</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="model in availableVideoModels" :key="model.id">
                <td><div class="d-flex align-center ga-3 py-2"><v-avatar color="deep-purple" variant="tonal" size="36"><v-icon size="20">mdi-movie-open-outline</v-icon></v-avatar><div><div class="font-weight-bold">{{ model.name }}</div><a :href="model.model_card_url" target="_blank" rel="noopener noreferrer" class="text-caption text-primary">License &amp; usage <v-icon size="12">mdi-open-in-new</v-icon></a></div></div></td>
                <td class="model-table__description">{{ model.description }}</td>
                <td><v-chip :color="model.supports_image ? 'success' : 'secondary'" variant="tonal" size="small">{{ model.supports_image ? 'Supported' : 'Text only' }}</v-chip></td>
                <td><v-chip :color="model.installed ? 'success' : 'secondary'" variant="tonal" size="small" :prepend-icon="model.installed ? 'mdi-check-circle' : 'mdi-download'">{{ model.installed ? 'Downloaded' : 'Downloads when used' }}</v-chip></td>
                <td class="text-right"><v-btn v-if="model.installed" color="error" variant="text" size="small" prepend-icon="mdi-delete-outline" :loading="removingVideoModelId === model.id" :disabled="videoGenerationActive" @click="confirmRemoveVideoModel(model)">Remove</v-btn></td>
              </tr>
            </tbody>
          </v-table>
          <v-list v-else class="model-list" lines="three">
            <v-list-item v-for="model in availableVideoModels" :key="model.id">
              <template #prepend><v-avatar color="deep-purple" variant="tonal" size="36"><v-icon size="20">mdi-movie-open-outline</v-icon></v-avatar></template>
              <v-list-item-title class="font-weight-bold">{{ model.name }}</v-list-item-title>
              <v-list-item-subtitle>{{ model.description }}<br><a :href="model.model_card_url" target="_blank" rel="noopener noreferrer" class="text-primary">License &amp; usage <v-icon size="12">mdi-open-in-new</v-icon></a></v-list-item-subtitle>
              <template #append><v-btn v-if="model.installed" color="error" icon="mdi-delete-outline" variant="text" size="small" :loading="removingVideoModelId === model.id" :disabled="videoGenerationActive" :aria-label="`Remove ${model.name}`" :title="`Remove ${model.name}`" @click="confirmRemoveVideoModel(model)" /></template>
            </v-list-item>
          </v-list>
        </v-card>

        <v-card v-if="page === 'about'">
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
            <v-alert v-if="display?.connected && !activeDisplayOnline" type="warning" variant="tonal" density="compact" class="ma-4" prepend-icon="mdi-monitor-off">
              {{ display.name }} is offline. It will receive the most recently prepared image after it reconnects; display and SD-card commands are unavailable until then.
            </v-alert>
            <v-alert v-if="!display?.connected" type="info" variant="tonal" density="compact" class="ma-4">
              Turn on the ESP32, connect it to the same local network as this computer, and confirm its configured server address points here. The display will appear automatically after it registers.
            </v-alert>
          </v-list>
        </v-card>

        <v-card v-if="page === 'display-experience'" class="settings-card">
          <v-card-title class="text-h5 pt-5">Display Experience</v-card-title>
          <v-card-text>
            <v-alert :type="display?.connected ? 'info' : 'warning'" variant="tonal" density="compact" class="display-context-bar mb-4" :prepend-icon="activeDisplayOnline ? 'mdi-monitor-check' : 'mdi-monitor-off'">
              <strong>Working with:</strong> {{ displayManagementLabel }}
              <div class="text-caption mt-1">New display and SD-card actions use this active display.</div>
            </v-alert>
            <v-alert v-if="display?.connected && !activeDisplayOnline" type="warning" variant="tonal" density="compact" class="mb-4" prepend-icon="mdi-monitor-off">
              {{ display.name }} is offline. The experience shown below was last reported by the display. Reconnect it to save or preview changes.
            </v-alert>
            <v-progress-linear v-if="displayExperienceLoading" indeterminate color="primary" class="mb-4" />
            <div class="d-flex flex-wrap ga-2 mb-5">
              <v-chip :color="activeDisplayOnline ? 'success' : 'warning'" variant="tonal" :prepend-icon="activeDisplayOnline ? 'mdi-monitor-check' : 'mdi-monitor-off'">
                {{ activeDisplayOnline ? 'Display online' : 'Display offline · last seen earlier' }}
              </v-chip>
              <v-chip :color="displayExperience.current_mode.startsWith('offline_') ? 'warning' : 'info'" variant="tonal" :prepend-icon="displayExperience.current_mode.startsWith('offline_') ? 'mdi-play-circle-outline' : 'mdi-cloud-check-outline'">
                {{ activeDisplayOnline ? 'Experience: ' : 'Last reported experience: ' }}{{ displayExperience.current_mode === 'offline_video_loop' ? 'Offline video loop' : displayExperience.current_mode === 'offline_slideshow' ? 'Offline slideshow' : 'Server controlled' }}
              </v-chip>
            </div>
            <p class="text-body-1 mb-5">When the display cannot reach ESPImageServer for a short time, it will use this saved experience. It returns to normal server control automatically when the connection is restored.</p>
            <v-form @submit.prevent="saveDisplayExperience">
              <v-select
                v-model="displayExperience.offline_experience"
                label="When ESPImageServer is unavailable"
                :items="[{ title: 'SD Card Slideshow', value: 'slideshow' }, { title: 'SD Card Video Loop', value: 'video_loop' }]"
                :disabled="!activeDisplayOnline"
                variant="outlined"
                class="mb-3"
              />
              <v-text-field v-if="displayExperience.offline_experience === 'slideshow'"
                v-model.number="displayExperienceIntervalSeconds"
                label="Change image every"
                type="number"
                min="0.5"
                max="3600"
                step="0.1"
                suffix="seconds"
                :disabled="!activeDisplayOnline"
                variant="outlined"
                class="mb-1"
              />
              <div v-if="displayExperience.offline_experience === 'slideshow'" class="d-flex flex-wrap ga-2 mb-3">
                <v-btn v-for="preset in [{ label: '1s', value: 1 }, { label: '2s', value: 2 }, { label: '5s', value: 5 }, { label: '15s', value: 15 }, { label: '30s', value: 30 }, { label: '1 min', value: 60 }]" :key="preset.label" size="small" variant="tonal" :disabled="!activeDisplayOnline" @click="displayExperienceIntervalSeconds = preset.value">{{ preset.label }}</v-btn>
              </div>
              <v-select
                v-model="displayExperience.slideshow_order"
                label="Order"
                :items="[{ title: 'Newest first', value: 'newest_first' }, { title: 'Oldest first', value: 'oldest_first' }]"
                :disabled="!activeDisplayOnline"
                variant="outlined"
                class="mb-3"
              />
              <v-btn type="submit" color="primary" :loading="displayExperienceSaving" :disabled="!activeDisplayOnline" prepend-icon="mdi-content-save">Save {{ display?.name || 'display' }} experience</v-btn>
              <v-btn type="button" class="ml-2" variant="tonal" color="primary" :disabled="!activeDisplayOnline || displayExperiencePreviewing" prepend-icon="mdi-play-circle-outline" @click="previewDisplayExperience">Preview {{ displayExperience.offline_experience === 'video_loop' ? 'video loop' : 'slideshow' }} on {{ display?.name || 'display' }}</v-btn>
              <div v-if="!activeDisplayOnline" class="text-caption text-medium-emphasis mt-3">Reconnect the display to save or preview these settings.</div>
              <v-alert v-if="displayExperienceStatus" type="success" variant="tonal" density="compact" class="mt-4">{{ displayExperienceStatus }}</v-alert>
              <v-alert v-if="displayExperienceError" type="error" variant="tonal" density="compact" class="mt-4">{{ displayExperienceError }}</v-alert>
            </v-form>
          </v-card-text>
        </v-card>

        <v-card v-if="page === 'sd-card'">
          <v-card-title class="d-flex align-center text-h5 pt-5">
            Display SD Card
            <v-spacer />
            <v-chip v-if="displaySdCard.available" :color="activeDisplayOnline ? 'success' : 'warning'" size="small" variant="tonal" prepend-icon="mdi-sd">
              {{ activeDisplayOnline ? 'Card ready' : 'Last reported card' }} · {{ displaySdCard.files?.length || 0 }} files
            </v-chip>
          </v-card-title>
          <v-card-text>
            <v-alert :type="display?.connected ? 'info' : 'warning'" variant="tonal" density="compact" class="display-context-bar mb-4" :prepend-icon="activeDisplayOnline ? 'mdi-monitor-check' : 'mdi-monitor-off'">
              <strong>Working with:</strong> {{ displayManagementLabel }}
              <div class="text-caption mt-1">New display and SD-card actions use this active display.</div>
            </v-alert>
            <v-alert v-if="display?.connected && !activeDisplayOnline" type="warning" variant="tonal" density="compact" class="mb-4" prepend-icon="mdi-monitor-off">
              {{ display.name }} is offline. This is its last reported SD-card list; reconnect it to refresh, play, save, or delete files.
            </v-alert>
            <v-alert v-if="!displaySdCard.available" type="warning" variant="tonal" density="compact" class="mb-4">
              Waiting for the display to report its SD card.
            </v-alert>
            <v-alert v-if="error" type="error" variant="tonal" density="compact" class="mb-4">{{ error }}</v-alert>
            <div class="d-flex flex-wrap ga-2 mb-4">
              <v-btn prepend-icon="mdi-refresh" :loading="displaySdCardLoading" :disabled="!activeDisplayOnline || deletingSdCardFile || deletingSdCardFiles" @click="refreshDisplaySdCard">Refresh {{ displaySdCardLabel }}</v-btn>
              <v-btn
                v-if="selectedSdCardFiles.length"
                color="error"
                variant="tonal"
                prepend-icon="mdi-delete-sweep-outline"
                :loading="deletingSdCardFiles"
                :disabled="!activeDisplayOnline || Boolean(displayingSdCardFile) || deletingSdCardFile"
                @click="confirmDeleteSelectedSdCardFiles"
              >
                Delete selected ({{ selectedSdCardFiles.length }})
              </v-btn>
              <v-btn
                v-if="selectedSdCardFiles.length"
                variant="text"
                :disabled="deletingSdCardFiles"
                @click="selectedSdCardFileNames = []"
              >
                Clear selection
              </v-btn>
            </div>
            <div v-if="displaySdCard.reported_at" class="text-caption text-medium-emphasis mb-4">
              Last confirmed by the display: {{ formatDateTime(displaySdCard.reported_at) }}
            </div>
            <v-progress-linear v-if="compact && displaySdCardLoading" indeterminate color="primary" class="mb-3" />
            <v-list v-if="compact" class="sd-card-mobile-list border rounded" lines="three">
              <v-list-item v-for="item in displaySdCard.files || []" :key="item.name">
                <template #prepend>
                  <div class="d-flex align-center ga-1">
                    <v-checkbox-btn
                      :model-value="selectedSdCardFileNames.includes(item.name)"
                      :disabled="!activeDisplayOnline || deletingSdCardFile || deletingSdCardFiles"
                      :aria-label="`Select ${item.name} for deletion`"
                      @update:model-value="setSdCardFileSelected(item.name, $event)"
                    />
                    <v-avatar v-if="item.thumbnail_available" rounded="sm" size="56">
                      <v-img :src="displaySdCardThumbnailUrl(item.name)" cover />
                    </v-avatar>
                    <v-avatar v-else color="surface-variant" rounded="sm" size="56">
                      <v-icon>{{ item.type === 'video' ? 'mdi-movie-open-outline' : 'mdi-image-outline' }}</v-icon>
                    </v-avatar>
                  </div>
                </template>
                <v-list-item-title class="text-break">{{ item.name }}</v-list-item-title>
                <v-list-item-subtitle>{{ item.type === 'video' ? 'Video' : 'Image' }} · {{ formatDateTime(item.created_at) }}</v-list-item-subtitle>
                <v-list-item-subtitle>{{ formatFileSize(item.size) }} · Saved on your display SD card</v-list-item-subtitle>
                <template #append>
                  <div class="d-flex flex-column">
                    <v-btn icon="mdi-play" size="small" color="primary" variant="text" :loading="displayingSdCardFile === item.name" :disabled="!activeDisplayOnline || Boolean(displayingSdCardFile) || deletingSdCardFile || deletingSdCardFiles" :aria-label="`Show ${item.name} on ${display?.name || 'display'}`" @click="showSDCardFileOnDisplay(item.name)" />
                    <v-btn icon="mdi-delete-outline" size="small" color="error" variant="text" :loading="deletingSdCardFile && sdCardFileToDelete?.name === item.name" :disabled="!activeDisplayOnline || Boolean(displayingSdCardFile) || deletingSdCardFile || deletingSdCardFiles" :aria-label="`Delete ${item.name} from ${displaySdCardLabel}`" @click="confirmDeleteDisplaySdCardFile(item)" />
                  </div>
                </template>
              </v-list-item>
              <div v-if="!(displaySdCard.files || []).length && !displaySdCardLoading" class="py-8 text-center text-medium-emphasis">No saved SD card images or videos yet.</div>
            </v-list>
            <v-data-table
              v-else
              :headers="sdCardTableHeaders"
              :items="displaySdCard.files || []"
              :loading="displaySdCardLoading"
              v-model:items-per-page="sdCardItemsPerPage"
              v-model="selectedSdCardFileNames"
              item-value="name"
              :show-select="activeDisplayOnline"
              select-strategy="all"
              hover
              density="comfortable"
              class="sd-card-table border rounded"
            >
              <template #item.thumbnail="{ item }">
                <v-avatar v-if="item.thumbnail_available" rounded="sm" size="56">
                  <v-img :src="displaySdCardThumbnailUrl(item.name)" cover />
                </v-avatar>
                <v-avatar v-else color="surface-variant" rounded="sm" size="56">
                  <v-icon>{{ item.type === 'video' ? 'mdi-movie-open-outline' : 'mdi-image-outline' }}</v-icon>
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
                  <v-tooltip :text="showOnDisplayLabel">
                    <template #activator="{ props }">
                      <v-btn
                        v-bind="props"
                        icon="mdi-play"
                        size="small"
                        color="primary"
                        variant="text"
                        :loading="displayingSdCardFile === item.name"
                        :disabled="!activeDisplayOnline || Boolean(displayingSdCardFile) || deletingSdCardFile || deletingSdCardFiles"
                        @click="showSDCardFileOnDisplay(item.name)"
                      />
                    </template>
                  </v-tooltip>
                  <v-tooltip :text="`Delete from ${displaySdCardLabel}`">
                    <template #activator="{ props }">
                      <v-btn v-bind="props" icon="mdi-delete-outline" size="small" color="error" variant="text" :loading="deletingSdCardFile && sdCardFileToDelete?.name === item.name" :disabled="!activeDisplayOnline || Boolean(displayingSdCardFile) || deletingSdCardFile || deletingSdCardFiles" @click="confirmDeleteDisplaySdCardFile(item)" />
                    </template>
                  </v-tooltip>
                </div>
              </template>
              <template #no-data>
                <div class="py-8 text-center text-medium-emphasis">No saved SD card images or videos yet.</div>
              </template>
            </v-data-table>
          </v-card-text>
        </v-card>

        <v-card v-if="page === 'settings'" class="settings-card">
          <v-card-title class="text-h5 pt-5">Settings</v-card-title>
          <v-card-text>
            <v-card v-if="!compact" variant="tonal" color="primary" class="mb-6">
              <v-card-title class="text-subtitle-1">Use from your phone</v-card-title>
              <v-card-text class="pt-0">
                <div class="text-body-2">Open ESPImageServer on another device connected to the same Wi-Fi network.</div>
                <div class="text-caption text-medium-emphasis mt-3">Phone address: {{ mobileAccessUrl }}</div>
                <div v-if="mobileAccessFallbackUrl" class="text-caption text-medium-emphasis mt-1">Fallback: {{ mobileAccessFallbackUrl }}</div>
              </v-card-text>
              <v-card-actions>
                <v-btn color="primary" variant="flat" prepend-icon="mdi-qrcode" @click="openMobileAccessDialog">Show QR code</v-btn>
                <v-btn variant="text" prepend-icon="mdi-content-copy" @click="copyMobileAccessUrl(mobileAccessUrl, 'Phone')">Copy address</v-btn>
              </v-card-actions>
              <v-alert v-if="mobileAccessCopyStatus" :type="mobileAccessCopyStatus.startsWith('Could not') ? 'warning' : 'success'" variant="tonal" density="compact" class="mx-4 mb-4">
                {{ mobileAccessCopyStatus }}
              </v-alert>
            </v-card>
            <v-form @submit.prevent="saveAppSettings">
              <template v-if="!compact">
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
                <div class="d-flex flex-wrap ga-2 mb-6">
                  <v-btn type="button" variant="tonal" prepend-icon="mdi-folder-search" :loading="choosingImageLibrary" @click="chooseImageLibrary">
                    Choose image library folder
                  </v-btn>
                  <v-btn type="button" variant="tonal" prepend-icon="mdi-folder-open" :loading="openingImageLibrary" @click="revealImageLibrary">
                    Open image library folder
                  </v-btn>
                </div>
              </template>
              <v-alert v-else type="info" variant="tonal" density="compact" class="mb-6">
                Image-library folders are managed on the computer running ESPImageServer. Use the desktop app to choose or open that folder.
              </v-alert>
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
              <v-slider
                v-model="videoJpegQuality"
                label="Video JPEG quality"
                min="2"
                max="20"
                step="1"
                thumb-label
                color="primary"
                class="mt-2"
              />
              <div class="text-body-2 text-medium-emphasis mb-5">
                Used when saving videos to the display SD card. Lower values retain more detail but create larger files; 10 is recommended.
              </div>
              <v-switch
                v-model="confirmDeletion"
                label="Ask before deleting saved images, videos, and SD card files"
                color="primary"
                hint="Turn this off to delete saved creations and display SD card files immediately."
                persistent-hint
                class="mb-5"
              />
              <v-btn type="submit" color="primary" :loading="settingsSaving" prepend-icon="mdi-content-save">Save settings</v-btn>
              <v-alert v-if="settingsStatus" type="success" variant="tonal" density="compact" class="mt-4">{{ settingsStatus }}</v-alert>
              <v-alert v-if="settingsError" type="error" variant="tonal" density="compact" class="mt-4">{{ settingsError }}</v-alert>
            </v-form>
          </v-card-text>
        </v-card>
      </v-container>
    </v-main>
    <v-navigation-drawer v-if="false"
      v-model="activityPanelOpen"
      class="activity-drawer"
      location="bottom"
      absolute
      temporary
      touchless
      :scrim="false"
      :height="compact ? '72vh' : 360"
    >
      <v-toolbar density="comfortable" color="surface">
        <v-icon class="ml-4 mr-3" icon="mdi-text-box-outline" />
        <v-toolbar-title class="text-subtitle-1">Diagnostics</v-toolbar-title>
        <v-btn icon="mdi-close" variant="text" size="small" aria-label="Close activity panel" @click="activityPanelOpen = false" />
      </v-toolbar>
      <v-tabs v-model="activityPanelTab" density="compact" color="primary">
          <v-tab v-if="false" value="queue" prepend-icon="mdi-format-list-numbered">Queue</v-tab>
          <v-tab value="logs" prepend-icon="mdi-text-box-outline">Diagnostics</v-tab>
        </v-tabs>
        <v-divider />
        <v-window v-model="activityPanelTab" class="activity-drawer__content">
          <v-window-item v-if="false" value="queue">
            <v-list v-if="generationQueue.some(job => ['queued', 'running', 'cancelling'].includes(job.status))" density="compact">
              <v-list-item v-for="job in generationQueue.filter(item => ['queued', 'running', 'cancelling'].includes(item.status))" :key="job.id">
                <template #prepend><v-icon :icon="job.kind === 'video' ? 'mdi-movie-open-outline' : 'mdi-image-outline'" /></template>
                <v-list-item-title>{{ job.kind === 'video' ? 'Video' : 'Image' }} · {{ job.metadata?.label || 'Generation request' }}</v-list-item-title>
                <v-list-item-subtitle>{{ job.status === 'queued' ? `Waiting · position ${job.queue_position}` : job.stage }}<span v-if="job.status !== 'queued' && job.progress"> · {{ job.progress }}%</span></v-list-item-subtitle>
                <template #append><v-btn icon="mdi-cancel" variant="text" color="warning" size="small" :loading="cancellingQueueJobId === job.id" :disabled="!job.cancellable || Boolean(cancellingQueueJobId)" :aria-label="`Cancel ${job.kind} job`" @click="cancelQueuedGeneration(job)" /></template>
              </v-list-item>
            </v-list>
            <div v-else class="pa-4 text-medium-emphasis">No image or video jobs are waiting.</div>
          </v-window-item>
          <v-window-item value="logs">
            <div class="d-flex justify-end ga-2 pa-2"><v-btn size="small" variant="text" prepend-icon="mdi-content-copy" @click="copyDiagnostics">Copy diagnostics</v-btn><v-btn size="small" variant="text" color="error" prepend-icon="mdi-delete-outline" @click="clearDiagnostics">Clear</v-btn></div>
            <v-list v-if="diagnostics.length" density="compact" class="activity-drawer__logs">
              <v-list-item v-for="entry in diagnostics" :key="`${entry.timestamp}-${entry.message}`" :class="entry.level === 'error' ? 'text-error' : ''">
                <v-list-item-title class="text-body-2">{{ entry.message }}</v-list-item-title>
                <v-list-item-subtitle>{{ new Date(entry.timestamp).toLocaleTimeString() }} · {{ entry.source }}</v-list-item-subtitle>
              </v-list-item>
            </v-list>
            <div v-else class="pa-4 text-medium-emphasis">No diagnostic events yet.</div>
          </v-window-item>
      </v-window>
    </v-navigation-drawer>
  </v-app>
</template>
