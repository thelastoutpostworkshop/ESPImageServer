// Use the live /displays response's online status, just like the app header.
// Match the USB identity so another active display cannot complete setup.
export function matchSetupDisplay(identity, displays) {
  if (!identity?.hardware_id || !identity.wifi_connected || !Array.isArray(displays)) return null
  const matches = displays.filter(d => d.hardware_id === identity.hardware_id)
  if (matches.length !== 1) return null
  const display = matches[0]
  return display.online === true && display.firmware_version === identity.firmware_version &&
    display.width === identity.width && display.height === identity.height
    ? display : null
}
