export function sdSaveProgressMessage(command) {
  if (command?.status === 'cancelling') return 'Cancelling save… waiting for the display to stop.'
  if (command?.status === 'cancelled') return 'Save cancelled.'
  if (command?.status === 'superseded') return 'Save replaced by another display command.'
  const progress = command?.progress
  if (!progress) return ''
  if (progress.stage === 'verifying') return 'Download complete. Checking the file written to the SD card…'
  const total = Number(progress.total_bytes), received = Number(progress.received_bytes)
  if (!Number.isFinite(total) || !Number.isFinite(received) || total <= 0) return 'Waiting for the display to receive the download…'
  return `Saving to SD card: ${Math.min(100, Math.max(0, Math.floor(received * 100 / total)))}% received…`
}

export function sdSaveCommandEndpoint(command) {
  const prefix = command.display_id && command.display_id !== '__legacy__' ? `/displays/${encodeURIComponent(command.display_id)}` : ''
  return `${prefix}/display-commands/${encodeURIComponent(command.id)}`
}
