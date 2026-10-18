import test from 'node:test'
import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import vm from 'node:vm'
import { ref } from 'vue'
import { createAppSettingsSaver } from '../src/appSettings.js'
import {
  imageQualityLevel, videoQualityLevel,
  imageQualityFromLevel, videoQualityFromLevel,
} from '../src/qualitySettings.js'

const source = await readFile(new URL('../src/App.vue', import.meta.url), 'utf8')

function functions(start, end) {
  const from = source.indexOf(start), to = source.indexOf(end, from + start.length)
  assert.ok(from >= 0 && to > from, `Missing production boundary: ${start} / ${end}`)
  return source.slice(from, to)
}

function deferred() {
  let resolve, reject
  const promise = new Promise((yes, no) => { resolve = yes; reject = no })
  return { promise, resolve, reject }
}

const response = values => ({ ok: true, json: async () => values })
const defaults = {
  image_library_location: 'C:\\Pictures\\ESPImageServer',
  jpeg_quality: 85, video_jpeg_quality: 10,
  auto_save_images: true, auto_save_videos: true, confirm_deletion: true,
  auto_check_firmware_updates: true, auto_check_app_updates: true,
  folder_actions: { choose: true, reveal: true },
}

// Execute the production handlers and serialized saver. All server/folder
// requests are fixtures; these tests never move the user's real library.
function setup(options = {}) {
  const requests = [], refreshes = []
  let persisted = { ...defaults, ...options.settings }
  const ui = vm.createContext({
    createAppSettingsSaver, Error,
    imageLibraryLocation: ref(defaults.image_library_location),
    savedImageLibraryLocation: ref(defaults.image_library_location),
    folderActions: ref({ choose: false, reveal: false }),
    jpegQuality: ref(85), videoJpegQuality: ref(10),
    autoSaveImages: ref(true), autoSaveVideos: ref(true), confirmDeletion: ref(true),
    autoCheckFirmwareUpdates: ref(true), autoCheckAppUpdates: ref(true),
    firmwareChecksEnabled: ref(true), appChecksEnabled: ref(true),
    autoSaveSaving: ref(false), autoSaveVideoSaving: ref(false), settingsSaving: ref(false),
    openingImageLibrary: ref(false), choosingImageLibrary: ref(false),
    settingsError: ref(''), settingsStatus: ref(''), error: ref(''), videoError: ref(''),
    window: options.desktop ? { espImageServerDesktop: options.desktop } : {},
    loadSavedImages: async () => { refreshes.push('images') },
    loadSavedVideos: async () => { refreshes.push('videos') },
    fetch: async (url, request = {}) => {
      const call = {
        url, method: request.method || 'GET',
        patch: request.body ? JSON.parse(request.body) : undefined,
      }
      requests.push(call)
      if (options.fetch) return options.fetch(call)
      if (url !== '/app-settings') assert.fail(`Unexpected settings request: ${url}`)
      if (call.method === 'PUT') persisted = { ...persisted, ...call.patch }
      return response({ ...persisted })
    },
  })
  vm.runInContext(
    functions('const appSettingRefs =', 'const mobileAccessDialog =') + '\n' +
    functions('async function loadAppSettings()', 'async function openMetadataPane()'),
    ui,
  )
  return { ui, requests, refreshes }
}

test('loading persisted settings restores all controls without writing them back', async () => {
  const { ui, requests } = setup({ settings: {
    jpeg_quality: 70, video_jpeg_quality: 17, confirm_deletion: false,
    auto_check_firmware_updates: false, auto_check_app_updates: false,
    auto_save_images: false, auto_save_videos: false,
  } })
  await ui.loadAppSettings()
  assert.deepEqual(requests.map(call => call.method), ['GET'])
  assert.equal(ui.jpegQuality.value, 70)
  assert.equal(ui.videoJpegQuality.value, 17)
  assert.equal(ui.confirmDeletion.value, false)
  assert.equal(ui.autoSaveImages.value, false)
  assert.equal(ui.autoSaveVideos.value, false)
  assert.equal(ui.firmwareChecksEnabled.value, false)
  assert.equal(ui.appChecksEnabled.value, false)
  assert.equal(ui.settingsSaving.value, false)
})

test('quality and switch changes save partial patches without a pending folder selection', async () => {
  const { ui, requests, refreshes } = setup()
  ui.setImageLibraryLocation('C:\\Pictures\\Unfinished')
  await ui.saveAppSetting('jpeg_quality', 75)
  await ui.saveAppSetting('video_jpeg_quality', 15)
  await ui.saveAppSetting('confirm_deletion', false)
  assert.deepEqual(requests.map(call => call.patch), [
    { jpeg_quality: 75 }, { video_jpeg_quality: 15 }, { confirm_deletion: false },
  ])
  assert.equal(ui.imageLibraryLocation.value, 'C:\\Pictures\\Unfinished')
  assert.equal(ui.savedImageLibraryLocation.value, defaults.image_library_location)
  assert.equal(ui.jpegQuality.value, 75)
  assert.equal(ui.videoJpegQuality.value, 15)
  assert.equal(ui.confirmDeletion.value, false)
  assert.deepEqual(refreshes, ['images'])
})

test('the common quality levels save the corresponding image and video encoder settings', async () => {
  const { ui, requests } = setup()
  for (const level of [1, 6, 10]) {
    await ui.saveAppSetting('jpeg_quality', imageQualityFromLevel(level))
    await ui.saveAppSetting('video_jpeg_quality', videoQualityFromLevel(level))
    assert.equal(imageQualityLevel(ui.jpegQuality.value), level)
    assert.equal(videoQualityLevel(ui.videoJpegQuality.value), level)
  }
  assert.deepEqual(requests.map(call => call.patch), [
    { jpeg_quality: 40 }, { video_jpeg_quality: 20 },
    { jpeg_quality: 73 }, { video_jpeg_quality: 10 },
    { jpeg_quality: 100 }, { video_jpeg_quality: 2 },
  ])
})

test('displaying approximate quality levels leaves legacy encoder settings unchanged', async () => {
  for (const settings of [
    { jpeg_quality: 85, video_jpeg_quality: 11 },
    { jpeg_quality: 1, video_jpeg_quality: 31 },
  ]) {
    const { ui, requests } = setup({ settings })
    await ui.loadAppSettings()
    assert.ok(imageQualityLevel(ui.jpegQuality.value) >= 1)
    assert.ok(videoQualityLevel(ui.videoJpegQuality.value) >= 1)
    await ui.saveAppSetting('confirm_deletion', false)
    assert.equal(ui.jpegQuality.value, settings.jpeg_quality)
    assert.equal(ui.videoJpegQuality.value, settings.video_jpeg_quality)
    assert.deepEqual(requests.filter(call => call.method === 'PUT').map(call => call.patch), [
      { confirm_deletion: false },
    ])
  }
})

test('a delayed quality response cannot overwrite the newer slider choice', async () => {
  const first = deferred(), second = deferred()
  const { ui, requests } = setup({ fetch: call => {
    assert.equal(call.method, 'PUT')
    return requests.length === 1 ? first.promise : second.promise
  } })
  const original = ui.saveAppSetting('jpeg_quality', 75)
  const latest = ui.saveAppSetting('jpeg_quality', 80)
  assert.equal(ui.jpegQuality.value, 80)
  assert.equal(requests.length, 1)
  first.resolve(response({ ...defaults, jpeg_quality: 75 }))
  await original
  assert.equal(ui.jpegQuality.value, 80)
  assert.deepEqual(requests.map(call => call.patch), [{ jpeg_quality: 75 }, { jpeg_quality: 80 }])
  assert.equal(ui.settingsSaving.value, true)
  second.resolve(response({ ...defaults, jpeg_quality: 80 }))
  await latest
  assert.equal(ui.jpegQuality.value, 80)
  assert.equal(ui.settingsSaving.value, false)
})

test('a failed change rolls back only its field and a later attempt still saves', async () => {
  const failure = deferred()
  let attempts = 0
  const { ui } = setup({ fetch: call => {
    if (++attempts === 1) return failure.promise
    return response({ ...defaults, ...call.patch })
  } })
  const changed = ui.saveAppSetting('jpeg_quality', 75)
  ui.videoJpegQuality.value = 17
  ui.setImageLibraryLocation('C:\\Pictures\\Pending selection')
  failure.reject(new Error('Connection lost'))
  await changed
  assert.equal(ui.jpegQuality.value, 85)
  assert.equal(ui.videoJpegQuality.value, 17)
  assert.equal(ui.imageLibraryLocation.value, 'C:\\Pictures\\Pending selection')
  assert.match(ui.settingsError.value, /Connection lost/)
  assert.equal(ui.settingsSaving.value, false)
  await ui.saveAppSetting('jpeg_quality', 80)
  assert.equal(ui.jpegQuality.value, 80)
  assert.equal(ui.settingsError.value, '')
  assert.match(ui.settingsStatus.value, /saved automatically/i)
})

test('two failed edits of the same field restore its last confirmed value', async () => {
  const first = deferred(), second = deferred()
  const { ui, requests } = setup({ fetch: () => requests.length === 1 ? first.promise : second.promise })
  const original = ui.saveAppSetting('jpeg_quality', 75)
  const latest = ui.saveAppSetting('jpeg_quality', 80)
  first.reject(new Error('First save failed'))
  await original
  assert.equal(ui.jpegQuality.value, 80)
  second.reject(new Error('Second save failed'))
  await latest
  assert.equal(ui.jpegQuality.value, 85)
  assert.match(ui.settingsError.value, /Second save failed/)
  assert.equal(ui.settingsSaving.value, false)
})

test('late initial settings loading preserves edits made while its GET was pending', async () => {
  const loaded = deferred(), saved = deferred()
  const { ui, requests } = setup({ fetch: call => call.method === 'GET' ? loaded.promise : saved.promise })
  const loading = ui.loadAppSettings()
  const changed = ui.saveAppSetting('jpeg_quality', 75)
  loaded.resolve(response({ ...defaults, video_jpeg_quality: 17 }))
  await loading
  assert.equal(ui.jpegQuality.value, 75)
  assert.equal(ui.videoJpegQuality.value, 17)
  assert.deepEqual(requests.map(call => call.method), ['GET', 'PUT'])
  saved.resolve(response({ ...defaults, jpeg_quality: 75 }))
  await changed
  assert.equal(ui.jpegQuality.value, 75)
})

test('late hydration restores the persisted baseline after an earlier edit failed', async () => {
  const loaded = deferred(), saved = deferred()
  const { ui } = setup({ fetch: call => call.method === 'GET' ? loaded.promise : saved.promise })
  const loading = ui.loadAppSettings()
  const changed = ui.saveAppSetting('jpeg_quality', 75)
  saved.reject(new Error('Save failed before settings loaded'))
  await changed
  loaded.resolve(response({ ...defaults, jpeg_quality: 70 }))
  await loading
  assert.equal(ui.jpegQuality.value, 70)
  assert.match(ui.settingsError.value, /Save failed before settings loaded/)
})

test('initial hydration started after an edit preserves the pending optimistic value', async () => {
  const saved = deferred()
  const { ui, requests } = setup({ fetch: call => call.method === 'GET'
    ? response({ ...defaults, video_jpeg_quality: 17 }) : saved.promise })
  const changed = ui.saveAppSetting('jpeg_quality', 75)
  await ui.loadAppSettings()
  assert.equal(ui.jpegQuality.value, 75)
  assert.equal(ui.videoJpegQuality.value, 17)
  assert.deepEqual(requests.map(call => call.method), ['PUT', 'GET'])
  saved.resolve(response({ ...defaults, jpeg_quality: 75 }))
  await changed
  assert.equal(ui.jpegQuality.value, 75)
})

for (const editBeforeLoading of [true, false]) {
  test(`initial hydration preserves a pending folder selected ${editBeforeLoading ? 'before' : 'during'} its GET`, async () => {
    const loaded = deferred()
    const { ui, requests } = setup({ fetch: () => loaded.promise })
    const draft = 'C:\\Pictures\\Selected new folder'
    if (editBeforeLoading) ui.setImageLibraryLocation(draft)
    const loading = ui.loadAppSettings()
    if (!editBeforeLoading) ui.setImageLibraryLocation(draft)
    loaded.resolve(response(defaults))
    await loading
    assert.equal(ui.imageLibraryLocation.value, draft)
    assert.equal(ui.savedImageLibraryLocation.value, defaults.image_library_location)
    assert.deepEqual(requests.map(call => call.method), ['GET'])
  })
}

for (const [key, inputName, enabledName] of [
  ['auto_check_firmware_updates', 'autoCheckFirmwareUpdates', 'firmwareChecksEnabled'],
  ['auto_check_app_updates', 'autoCheckAppUpdates', 'appChecksEnabled'],
]) {
  test(`${key} affects automatic checks only after the server confirms each change`, async () => {
    const first = deferred(), second = deferred()
    const { ui, requests } = setup({ fetch: () => requests.length === 1 ? first.promise : second.promise })
    const disabled = ui.saveAppSetting(key, false)
    assert.equal(ui[inputName].value, false)
    assert.equal(ui[enabledName].value, true)
    const enabled = ui.saveAppSetting(key, true)
    first.resolve(response({ ...defaults, [key]: false }))
    await disabled
    assert.equal(ui[inputName].value, true)
    assert.equal(ui[enabledName].value, false)
    second.resolve(response({ ...defaults, [key]: true }))
    await enabled
    assert.equal(ui[enabledName].value, true)
  })
}

test('existing automatic-save and deletion-dialog handlers share ordered partial writes', async () => {
  const first = deferred()
  const { ui, requests } = setup({ fetch: call => requests.length === 1
    ? first.promise : response({ ...defaults, auto_save_images: false, ...call.patch }) })
  const images = ui.setAutoSaveImages(false)
  const videos = ui.setAutoSaveVideos(false)
  const deletion = ui.setDeleteConfirmation(false)
  assert.equal(requests.length, 1)
  first.resolve(response({ ...defaults, auto_save_images: false }))
  await Promise.all([images, videos, deletion])
  assert.deepEqual(requests.map(call => call.patch), [
    { auto_save_images: false }, { auto_save_videos: false, confirm_deletion: false },
  ])
  assert.equal(ui.autoSaveImages.value, false)
  assert.equal(ui.autoSaveVideos.value, false)
  assert.equal(ui.confirmDeletion.value, false)
})

test('saving a selected library path saves it once and refreshes images and videos', async () => {
  const moved = deferred()
  const { ui, requests, refreshes } = setup({ fetch: () => moved.promise })
  const location = 'C:\\Pictures\\New library'
  ui.setImageLibraryLocation(location)
  assert.equal(requests.length, 0)
  const changed = ui.saveImageLibraryLocation()
  await ui.saveImageLibraryLocation()
  assert.deepEqual(requests.map(call => call.patch), [{ image_library_location: location }])
  assert.equal(ui.savedImageLibraryLocation.value, defaults.image_library_location)
  moved.resolve(response({ ...defaults, image_library_location: location }))
  await changed
  assert.equal(ui.savedImageLibraryLocation.value, location)
  assert.equal(ui.imageLibraryLocation.value, location)
  assert.deepEqual(refreshes.sort(), ['images', 'videos'])
  await ui.saveImageLibraryLocation()
  assert.equal(requests.length, 1)
})

test('returning to the original library path queues that move behind the pending relocation', async () => {
  const first = deferred(), second = deferred()
  const { ui, requests } = setup({ fetch: () => requests.length === 1 ? first.promise : second.promise })
  const originalLocation = defaults.image_library_location
  const nextLocation = 'C:\\Pictures\\Temporary library'
  ui.setImageLibraryLocation(nextLocation)
  const moved = ui.saveImageLibraryLocation()
  ui.setImageLibraryLocation(originalLocation)
  const returned = ui.saveImageLibraryLocation()
  assert.equal(requests.length, 1)
  first.resolve(response({ ...defaults, image_library_location: nextLocation }))
  await moved
  assert.equal(ui.imageLibraryLocation.value, originalLocation)
  assert.deepEqual(requests.map(call => call.patch), [
    { image_library_location: nextLocation }, { image_library_location: originalLocation },
  ])
  second.resolve(response(defaults))
  await returned
  assert.equal(ui.imageLibraryLocation.value, originalLocation)
  assert.equal(ui.savedImageLibraryLocation.value, originalLocation)
})

for (const desktop of [false, true]) {
  test(`${desktop ? 'desktop' : 'server'} folder chooser saves its selection immediately`, async () => {
    const location = 'C:\\Pictures\\Chosen library'
    const { ui, requests } = setup({
      desktop: desktop ? { chooseImageLibrary: async () => location } : undefined,
      fetch: call => call.url.endsWith('/choose')
        ? response({ selected: true, image_library_location: location })
        : response({ ...defaults, image_library_location: location }),
    })
    await ui.chooseImageLibrary()
    assert.deepEqual(requests.filter(call => call.method === 'PUT').map(call => call.patch), [
      { image_library_location: location },
    ])
    assert.equal(ui.savedImageLibraryLocation.value, location)
    assert.equal(ui.choosingImageLibrary.value, false)
  })

  test(`${desktop ? 'desktop' : 'server'} folder chooser cancellation leaves the location unchanged`, async () => {
    const { ui, requests } = setup({
      desktop: desktop ? { chooseImageLibrary: async () => null } : undefined,
      fetch: call => {
        assert.ok(call.url.endsWith('/choose'))
        return response({ selected: false })
      },
    })
    await ui.chooseImageLibrary()
    assert.equal(requests.filter(call => call.method === 'PUT').length, 0)
    assert.equal(ui.imageLibraryLocation.value, defaults.image_library_location)
    assert.equal(ui.savedImageLibraryLocation.value, defaults.image_library_location)
    assert.equal(ui.choosingImageLibrary.value, false)
  })

  test(`${desktop ? 'desktop' : 'server'} folder chooser ignores repeat clicks until selection and relocation finish`, async () => {
    const selection = deferred(), relocation = deferred(), savingStarted = deferred()
    const location = 'C:\\Pictures\\Chosen library'
    let dialogs = 0
    const { ui, requests } = setup({
      desktop: desktop ? { chooseImageLibrary: () => { dialogs += 1; return selection.promise } } : undefined,
      fetch: call => {
        if (call.url.endsWith('/choose')) {
          dialogs += 1
          return selection.promise
        }
        assert.equal(call.method, 'PUT')
        savingStarted.resolve()
        return relocation.promise
      },
    })
    const choosing = ui.chooseImageLibrary()
    await ui.chooseImageLibrary()
    assert.equal(dialogs, 1)
    assert.equal(ui.choosingImageLibrary.value, true)
    selection.resolve(desktop ? location : response({ selected: true, image_library_location: location }))
    await savingStarted.promise
    await ui.chooseImageLibrary()
    assert.equal(dialogs, 1)
    assert.equal(ui.choosingImageLibrary.value, true)
    assert.equal(ui.savedImageLibraryLocation.value, defaults.image_library_location)
    relocation.resolve(response({ ...defaults, image_library_location: location }))
    await choosing
    assert.equal(ui.choosingImageLibrary.value, false)
    assert.equal(ui.savedImageLibraryLocation.value, location)
    assert.deepEqual(requests.filter(call => call.method === 'PUT').map(call => call.patch), [
      { image_library_location: location },
    ])
  })

  test(`${desktop ? 'desktop' : 'server'} failed relocation preserves the confirmed path and can be retried through the chooser`, async () => {
    const location = 'C:\\Pictures\\Chosen library'
    let attempts = 0
    const { ui, refreshes } = setup({
      desktop: desktop ? { chooseImageLibrary: async () => location } : undefined,
      fetch: call => {
        if (call.url.endsWith('/choose')) return response({ selected: true, image_library_location: location })
        assert.equal(call.method, 'PUT')
        assert.equal(call.patch.image_library_location, location)
        if (++attempts === 1) throw new Error('Choose an empty folder')
        return response({ ...defaults, image_library_location: location })
      },
    })
    await ui.chooseImageLibrary()
    assert.equal(ui.savedImageLibraryLocation.value, defaults.image_library_location)
    assert.equal(ui.choosingImageLibrary.value, false)
    assert.match(ui.settingsError.value, /empty folder/)
    assert.deepEqual(refreshes, [])
    await ui.chooseImageLibrary()
    assert.equal(ui.savedImageLibraryLocation.value, location)
    assert.equal(ui.choosingImageLibrary.value, false)
    assert.equal(ui.settingsError.value, '')
    assert.equal(attempts, 2)
    assert.deepEqual(refreshes.sort(), ['images', 'videos'])
  })

  test(`${desktop ? 'desktop' : 'server'} confirmed chooser path survives a late settings response`, async () => {
    const loaded = deferred()
    const location = 'C:\\Pictures\\Chosen library'
    const { ui } = setup({
      desktop: desktop ? { chooseImageLibrary: async () => location } : undefined,
      fetch: call => {
        if (call.method === 'GET') return loaded.promise
        if (call.url.endsWith('/choose')) return response({ selected: true, image_library_location: location })
        return response({ ...defaults, image_library_location: location })
      },
    })
    const loading = ui.loadAppSettings()
    await ui.chooseImageLibrary()
    assert.equal(ui.savedImageLibraryLocation.value, location)
    loaded.resolve(response(defaults))
    await loading
    assert.equal(ui.savedImageLibraryLocation.value, location)
    assert.equal(ui.imageLibraryLocation.value, location)
  })
}

test('a failed library move keeps the selected path available for retry', async () => {
  let attempts = 0
  const { ui } = setup({ fetch: call => ++attempts === 1
    ? Promise.reject(new Error('Choose an empty folder'))
    : response({ ...defaults, image_library_location: call.patch.image_library_location }) })
  const location = 'C:\\Pictures\\Chosen library'
  ui.setImageLibraryLocation(location)
  await ui.saveImageLibraryLocation()
  assert.equal(ui.savedImageLibraryLocation.value, defaults.image_library_location)
  assert.equal(ui.imageLibraryLocation.value, location)
  assert.match(ui.settingsError.value, /empty folder/)
  await ui.saveImageLibraryLocation()
  assert.equal(ui.savedImageLibraryLocation.value, location)
  assert.equal(attempts, 2)
})
