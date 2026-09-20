import { SerialPort } from 'serialport'

// Syntax validation is a first filter, not permission to open a device.
// Operations must also match the exact path returned by current enumeration.
export function isSerialPortPath(value) {
  return typeof value === 'string' && value.length <= 256 &&
    /^(?:COM[1-9]\d*|\/dev\/(?:tty|cu\.)[A-Za-z0-9._-]+)$/.test(value)
}

export function requireDetectedPort(port, ports) {
  const detected = isSerialPortPath(port) && ports?.find(candidate => candidate.port === port)
  if (!detected) throw new Error('USB serial port is no longer available. Refresh ports and select the display again.')
  return detected
}

export async function serialPorts(list = () => SerialPort.list()) {
  const seen = new Set()
  return (await list()).filter(p => {
    if (!isSerialPortPath(p.path) || seen.has(p.path)) return false
    seen.add(p.path)
    return true
  }).map(p => ({
    port: p.path, label: `${p.path}${p.manufacturer ? ` — ${p.manufacturer}` : ''}`,
    serialNumber: p.serialNumber || '', vendorId: p.vendorId || '', productId: p.productId || ''
  }))
}
