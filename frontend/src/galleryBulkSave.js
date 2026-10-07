import { sdSaveProgressMessage } from './sdSaveProgress.js'

export function gallerySelectionKey(item) {
  return JSON.stringify([item.type, item.id])
}

export function selectAllGalleryItems(items) {
  return [...new Set(items.map(gallerySelectionKey))]
}

export function selectedGalleryItems(items, selectedKeys) {
  const selected = new Set(selectedKeys)
  const seen = new Set()
  return items.filter(item => {
    const key = gallerySelectionKey(item)
    if (!selected.has(key) || seen.has(key)) return false
    seen.add(key)
    return true
  })
}

// Keep the count and submitted items limited to the current gallery filter.
export function filterGallerySelection(selectedKeys, items) {
  const visible = new Set(selectAllGalleryItems(items))
  return [...new Set(selectedKeys)].filter(key => visible.has(key))
}

export function reconcileGallerySelection(selectedKeys, batch) {
  const confirmed = new Set((batch?.items || [])
    .filter(item => item.status === 'saved' || item.status === 'already_saved')
    .map(gallerySelectionKey))
  return selectedKeys.filter(key => !confirmed.has(key))
}

export function isGalleryBulkSaveActive(batch) {
  return batch?.status === 'running' || batch?.status === 'cancelling'
}

export function galleryBulkSaveProgressMessage(batch) {
  if (!batch) return ''
  const total = Math.max(0, Number(batch.total) || 0)
  const saved = Math.max(0, Number(batch.saved) || 0)
  const skipped = Math.max(0, Number(batch.skipped) || 0)
  const remaining = Math.max(0, total - saved - skipped)
  const counts = `${saved} saved, ${skipped} already on the SD card, ${remaining} remaining.`
  if (batch.status === 'cancelling') {
    return `Cancelling bulk save… waiting for the display to stop. ${counts}`
  }
  if (batch.status === 'cancelled') return `Bulk save cancelled. ${counts}`
  if (batch.status === 'failed') return `Bulk save stopped. ${counts}${batch.detail ? ` ${batch.detail}` : ''}`
  if (batch.status === 'complete') return `Bulk save complete. ${counts}`
  const index = Math.min(total, Math.max(0, Number(batch.current_index) || 0))
  const progress = sdSaveProgressMessage(batch.current_command)
  const stage = index > 0 ? `Saving item ${index} of ${total}.` : `Checking SD card · ${total} selected.`
  return `${stage} ${progress || counts}`
}
