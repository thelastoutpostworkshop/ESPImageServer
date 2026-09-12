// A global "active display" and a cached online badge are not setup evidence.
// Match the USB identity and require LAN contact during this verification run.
export function matchSetupDisplay(identity, displays, since, now = Date.now()) {
  if (!identity?.wifi_connected || !Array.isArray(displays)) return null
  const matches = displays.filter(d => d.hardware_id === identity.hardware_id)
  if (matches.length !== 1) return null
  const display = matches[0], lastSeen = Date.parse(display.last_seen)
  return display.online === true && display.firmware_version === identity.firmware_version &&
    display.width === identity.width && display.height === identity.height &&
    Number.isFinite(lastSeen) && lastSeen >= since && lastSeen <= now + 5000 && now - lastSeen <= 15000
    ? display : null
}
