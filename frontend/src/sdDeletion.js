export function requireSdCardCommandAvailable(deletionActive) {
  if (deletionActive) throw new Error('Wait for the current SD-card deletion to finish before sending another display command.')
}

// A DELETE is sent once. Subsequent requests only read its result or a newer
// inventory, so a slow or interrupted connection cannot duplicate the action.
export async function waitForSdCardDeletion({
  commandEndpoint,
  inventoryEndpoint,
  filename,
  baselineReportVersion,
  onWaiting = () => {},
  fetchImpl = fetch,
  wait = milliseconds => new Promise(resolve => window.setTimeout(resolve, milliseconds)),
  now = () => Date.now(),
  timeoutMs = 90_000,
}) {
  const deadline = now() + timeoutMs
  const baseline = Number(baselineReportVersion)
  const canReconcile = baselineReportVersion !== null && baselineReportVersion !== undefined && Number.isFinite(baseline) && baseline >= 0
  let nextInventoryCheck = 0
  for (let attempt = 0; attempt < Math.ceil(timeoutMs / 500) && now() < deadline; attempt += 1) {
    await wait(Math.min(500, Math.max(0, deadline - now())))
    if (now() >= deadline) break
    const read = async endpoint => {
      const response = await fetchImpl(endpoint, {
        cache: 'no-store',
        signal: AbortSignal.timeout(Math.max(1, Math.min(5000, deadline - now()))),
      })
      if (!response.ok) throw new Error(`Request failed (${response.status})`)
      return response.json()
    }
    let result
    try { result = await read(commandEndpoint) }
    catch { onWaiting('Connection interrupted. Still checking this file…') }
    if (result?.status === 'complete') return { confirmedBy: 'command' }
    if (['failed', 'cancelled', 'superseded'].includes(result?.status)) {
      throw new Error(result.detail || `The display could not delete ${filename}`)
    }
    if (result) onWaiting('Waiting for the display to confirm this file…')
    if (canReconcile && now() >= nextInventoryCheck && now() < deadline) {
      nextInventoryCheck = now() + 2000
      try {
        const report = await read(inventoryEndpoint)
        const version = Number(report.report_version)
        if (report.available === true && report.inventory_refresh_pending !== true && Array.isArray(report.files) &&
          report.files.every(file => typeof file?.name === 'string' && file.name.length > 0) && Number.isFinite(version) && version > baseline &&
          !report.files.some(file => file?.name === filename)) {
          return { confirmedBy: 'inventory', report }
        }
      } catch { /* A missing inventory is not proof of deletion. Keep checking. */ }
    }
  }
  throw new Error(`The display has not confirmed deleting ${filename}. Check its SD card before trying again; this file may already have been removed.`)
}
