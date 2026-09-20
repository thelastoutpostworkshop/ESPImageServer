export function generationJobDetail(job) {
  if (!job) return ''
  if (job.status === 'queued') return `Waiting in queue${job.queue_position ? ` · position ${job.queue_position}` : ''}`
  const seconds = Math.max(0, Math.floor(Number(job.elapsed_seconds) || 0))
  const elapsed = seconds < 60 ? `${seconds}s` : `${Math.floor(seconds / 60)}m ${seconds % 60}s`
  if (job.status === 'cancelling') {
    return `Cancellation requested · ${job.stage} · ${elapsed} elapsed. Waiting for the current operation to return; model loading and GPU operations can take time. The next job will wait until this one stops.`
  }
  const steps = job.steps > 0 && job.stage?.startsWith('Generating') ? ` · Step ${job.step} of ${job.steps}` : ''
  return `${job.error || job.stage}${steps} · ${elapsed} elapsed`
}

export function generationHasMeasuredProgress(job) {
  return job?.status === 'running' && job.steps > 0
}
