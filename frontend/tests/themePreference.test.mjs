import test from 'node:test'
import assert from 'node:assert/strict'
import { THEME_PREFERENCE_KEY, loadThemePreference, saveThemePreference } from '../src/themePreference.js'

function storageFor(values) {
  return {
    getItem: key => values.get(key) ?? null,
    setItem: (key, value) => values.set(key, String(value)),
  }
}

function withWindow(value, run) {
  const original = Object.getOwnPropertyDescriptor(globalThis, 'window')
  Object.defineProperty(globalThis, 'window', { configurable: true, value })
  try { return run() }
  finally {
    if (original) Object.defineProperty(globalThis, 'window', original)
    else delete globalThis.window
  }
}

for (const selection of ['light', 'dark']) {
  test(`${selection} preference survives a new storage wrapper after reload`, () => {
    const persisted = new Map([[THEME_PREFERENCE_KEY, selection === 'light' ? 'dark' : 'light']])
    assert.equal(saveThemePreference(selection, storageFor(persisted)), true)
    assert.equal(loadThemePreference(storageFor(persisted)), selection)
  })
}

test('browser storage is acquired safely on each call and restores a saved selection', () => {
  const persisted = new Map()
  withWindow({ localStorage: storageFor(persisted) }, () => {
    assert.equal(loadThemePreference(), 'dark')
    assert.equal(saveThemePreference('light'), true)
  })
  withWindow({ localStorage: storageFor(persisted) }, () => {
    assert.equal(loadThemePreference(), 'light')
    assert.equal(saveThemePreference('dark'), true)
  })
  withWindow({ localStorage: storageFor(persisted) }, () => {
    assert.equal(loadThemePreference(), 'dark')
  })
})

test('missing and invalid stored preferences fall back to dark', () => {
  assert.equal(loadThemePreference(storageFor(new Map())), 'dark')
  for (const value of ['', 'system', 'Light', 'DARK', 'true', ' light ', '{"theme":"light"}']) {
    assert.equal(loadThemePreference(storageFor(new Map([[THEME_PREFERENCE_KEY, value]]))), 'dark', value)
  }
})

test('theme updates preserve unrelated UI preferences', () => {
  const persisted = new Map([
    ['esp-image-server.active-display', 'screen-one'],
    ['esp-image-server.activity-panel-open', 'true'],
  ])
  const unrelated = [...persisted]
  const storage = storageFor(persisted)
  assert.equal(saveThemePreference('light', storage), true)
  assert.equal(saveThemePreference('dark', storage), true)
  assert.deepEqual([...persisted].filter(([key]) => key !== THEME_PREFERENCE_KEY), unrelated)
})

test('separate clients retain independent themes', () => {
  const desktopValues = new Map()
  const phoneValues = new Map()
  assert.equal(saveThemePreference('light', storageFor(desktopValues)), true)
  assert.equal(saveThemePreference('dark', storageFor(phoneValues)), true)
  assert.equal(loadThemePreference(storageFor(desktopValues)), 'light')
  assert.equal(loadThemePreference(storageFor(phoneValues)), 'dark')
})

test('invalid writes cannot overwrite a valid stored selection', () => {
  const persisted = new Map([[THEME_PREFERENCE_KEY, 'light']])
  const storage = storageFor(persisted)
  for (const value of [undefined, null, '', 'system', 'LIGHT', false, 1, {}, ['dark']]) {
    assert.equal(saveThemePreference(value, storage), false)
    assert.equal(loadThemePreference(storage), 'light')
  }
})

test('failed storage operations use a safe default and report an unsuccessful save', () => {
  const inaccessible = {
    getItem() { throw new Error('Storage access denied') },
    setItem() { throw new Error('Storage quota exceeded') },
  }
  assert.equal(loadThemePreference(inaccessible), 'dark')
  assert.equal(saveThemePreference('light', inaccessible), false)
})

test('an inaccessible browser storage getter is safely handled for loading and saving', () => {
  const browser = Object.defineProperty({}, 'localStorage', {
    get() { throw new Error('Storage access denied') },
  })
  withWindow(browser, () => {
    assert.equal(loadThemePreference(), 'dark')
    assert.equal(saveThemePreference('light'), false)
  })
})

test('a missing browser storage environment is safe', () => {
  withWindow(undefined, () => {
    assert.equal(loadThemePreference(), 'dark')
    assert.equal(saveThemePreference('light'), false)
  })
})
