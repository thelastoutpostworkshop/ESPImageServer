export function sdSaveCloseDialog({ unknown = false } = {}) {
  return {
    type: 'warning',
    title: unknown ? 'Could not check SD-card saves' : 'SD-card save in progress',
    message: unknown ? 'The display save status could not be checked.' : 'A display is still saving to its SD card.',
    detail: unknown
      ? 'Keep ESPImageServer open and try closing again once the local server responds.'
      : 'Wait for the save to finish, or cancel it in the app and wait for the display to confirm cancellation before closing ESPImageServer.',
    buttons: ['Keep open'],
    defaultId: 0,
    cancelId: 0,
    noLink: true,
  }
}

// The server reports active saves across every display. Never reuse a previous
// idle result: a save may have started while another close dialog was open.
export function createSdSaveCloseGuard({ readSaves, notify, onError = () => {} }) {
  let pending = null
  return {
    get pending() { return pending !== null },
    request() {
      if (pending) return pending
      pending = Promise.resolve().then(async () => {
        let saves = [], unknown = false
        try {
          saves = await readSaves()
          if (!Array.isArray(saves) || saves.some(save => !save || typeof save !== 'object' || Array.isArray(save))) {
            throw new Error('Invalid SD-card save status')
          }
        } catch {
          saves = []
          unknown = true
        }
        if (!unknown && !saves.length) return true
        await notify({ saves, unknown })
        return false
      }).catch(error => {
        onError(error)
        return false
      }).finally(() => { pending = null })
      return pending
    },
  }
}
