// Keep settings writes in order, retaining the latest edits made during a save.
export function createAppSettingsSaver({ request, onState = () => {} }) {
  let pending = null
  let waiters = []
  let saving = false
  let error = null
  let saved = false

  const publish = () => onState({ saving, error, saved })

  async function drain() {
    while (pending !== null) {
      const changes = pending
      const batch = waiters
      pending = null
      waiters = []
      try {
        const result = await request(changes)
        batch.forEach(({ resolve }) => resolve(result))
      } catch (failure) {
        error = failure instanceof Error ? failure : new Error(String(failure))
        batch.forEach(({ reject }) => reject(error))
        publish()
      }
    }
    saving = false
    saved = error === null
    publish()
  }

  return {
    save(changes) {
      if (!changes || Object.keys(changes).length === 0) return Promise.resolve(null)
      pending = { ...pending, ...changes }
      error = null
      saved = false
      const result = new Promise((resolve, reject) => waiters.push({ resolve, reject }))
      if (!saving) {
        saving = true
        publish()
        void drain()
      } else {
        publish()
      }
      return result
    },
  }
}
