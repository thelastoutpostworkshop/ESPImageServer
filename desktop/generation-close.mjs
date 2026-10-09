const activeStatuses = new Set(['queued', 'running', 'cancelling'])

export function generationCloseDialog({ unknown = false, stopsGeneration = true, closesApplication = true } = {}) {
  const action = `Do you want to close the ${closesApplication ? 'application' : 'window'}?`
  return {
    type: 'warning',
    title: 'Close ESPImageServer?',
    message: unknown ? 'Generation status could not be checked.' : 'Image or video generation is still running or queued.',
    detail: stopsGeneration
      ? `${unknown ? 'Closing may stop' : 'Closing will stop'} unfinished generation and discard waiting jobs. ${action}`
      : `Generation will continue in the background. ${action}`,
    buttons: ['Keep open', 'Close anyway'],
    defaultId: 0,
    cancelId: 0,
    noLink: true,
  }
}

// One decision covers the window close and the application quit that follows it.
export function createGenerationCloseGuard({ readJobs, confirm, onError = () => {} }) {
  let approved = false
  let pending = null
  let revision = 0

  return {
    get approved() { return approved },
    get pending() { return pending !== null },
    reset() { approved = false; revision += 1 },
    request() {
      if (approved) return Promise.resolve(true)
      if (pending) return pending
      const currentRevision = revision
      pending = Promise.resolve().then(async () => {
        let jobs = [], unknown = false
        try {
          const queue = await readJobs()
          if (!Array.isArray(queue)) throw new Error('Invalid generation queue response')
          jobs = queue.filter(job => job && activeStatuses.has(job.status))
        } catch {
          unknown = true
        }
        if (currentRevision !== revision) return false
        const allowed = jobs.length || unknown ? await confirm({ jobs, unknown }) === true : true
        if (currentRevision !== revision) return false
        approved = allowed
        return allowed
      }).catch(error => {
        onError(error)
        return false
      }).finally(() => { pending = null })
      return pending
    },
  }
}
