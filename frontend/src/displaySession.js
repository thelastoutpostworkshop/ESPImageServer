export function displayConnectionLabel(target) {
  if (target?.online) return 'Online'
  return target?.seen_this_session ? 'Offline' : 'Not seen this session'
}

export function sessionDisplayId(displays, selectedId, initial = false) {
  const selected = displays.find(target => target.id === selectedId)
  if (selected?.online) return selected.id
  const online = displays.find(target => target.online)
  if (online) return online.id
  return selected && (!initial || selected.seen_this_session) ? selected.id : ''
}
