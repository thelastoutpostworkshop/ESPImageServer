export const THEME_PREFERENCE_KEY = 'esp-image-server.theme'

export function loadThemePreference(storage) {
  try {
    return (storage ?? window.localStorage).getItem(THEME_PREFERENCE_KEY) === 'light' ? 'light' : 'dark'
  } catch {
    return 'dark'
  }
}

export function saveThemePreference(theme, storage) {
  if (theme !== 'dark' && theme !== 'light') return false
  try {
    (storage ?? window.localStorage).setItem(THEME_PREFERENCE_KEY, theme)
    return true
  } catch {
    return false
  }
}
