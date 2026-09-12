import { randomUUID } from 'node:crypto'
import { SerialPort } from 'serialport'
import { StringDecoder } from 'node:string_decoder'

export function responseDecoder(id, onResult, maxLength = 2048) {
  let line = '', overflow = false
  const utf8 = new StringDecoder('utf8')
  return chunk => {
    for (const character of typeof chunk === 'string' ? chunk : utf8.write(chunk)) {
      if (character === '\n') {
        if (!overflow) {
          const start = line.indexOf('@ESPIMAGE ')
          if (start >= 0) {
            let message
            try { message = JSON.parse(line.slice(start + 10)) } catch { /* ignore damaged/log lines */ }
            if (message && (id === null || message.id === id)) onResult(message)
          }
        }
        line = ''; overflow = false
      } else if (line.length < maxLength && !overflow) line += character
      else overflow = true
    }
  }
}

export function validateIdentity(message) {
  if (message.protocol !== 1 || !message.ok) throw new Error('Unsupported USB identification protocol.')
  const r = message.result
  if (!r || r.protocol_version !== 1 || !/^[a-f0-9]{12}$/.test(r.hardware_id) ||
      !['JC4827W543', 'ST7701_320X820', 'ESP32_C6_LCD_147', 'CHEAP_YELLOW_DISPLAY'].includes(r.board_target) ||
      typeof r.board_name !== 'string' || r.board_name.length > 100 ||
      typeof r.firmware_version !== 'string' || !/^\d+\.\d+\.\d+(?:[-+][a-z0-9.-]+)?$/i.test(r.firmware_version) ||
      !Array.isArray(r.capabilities) || !r.capabilities.includes('hello') || !r.capabilities.includes('status') ||
      !Number.isInteger(r.width) || r.width <= 0 || r.width > 4096 ||
      !Number.isInteger(r.height) || r.height <= 0 || r.height > 4096 ||
      typeof r.wifi_configured !== 'boolean' || typeof r.wifi_connected !== 'boolean') {
    throw new Error('Invalid USB firmware identity response.')
  }
  // Whitelist fields; never forward arbitrary serial data/passwords to the UI.
  return { ...Object.fromEntries(['hardware_id', 'board_target', 'board_name', 'firmware_version',
    'protocol_version', 'width', 'height', 'wifi_configured', 'wifi_connected'].map(key => [key, r[key]])),
    capabilities: r.capabilities.filter(c => ['hello', 'status', 'wifi_scan', 'wifi_connect', 'wifi_cancel', 'wifi_status'].includes(c)) }
}

export async function identifyPort(portName, { timeout = 5000, createPort = options => new SerialPort(options) } = {}) {
  if (!/^COM\d+$/.test(portName)) throw new Error('Select a valid COM port.')
  const port = createPort({ path: portName, baudRate: 115200, autoOpen: false, lock: true, rtscts: false })
  const id = randomUUID()
  let timer, retry, settled = false, opening = true, finishOpen
  return new Promise((resolve, reject) => {
    const finish = (error, value) => {
      if (settled) return
      settled = true; clearTimeout(timer); clearInterval(retry)
      const done = closeError => error || closeError ? reject(error || closeError) : resolve({ ...value, port: portName })
      const release = () => { if (port.isOpen) port.close(done); else done() }
      // An open already in flight must finish and close before releasing the
      // application operation lock, even if its handshake deadline elapsed.
      if (opening) finishOpen = release
      else release()
    }
    port.on('error', error => finish(error))
    port.on('close', () => { if (!settled) finish(new Error('USB disconnected during identification. Refresh ports and retry.')) })
    port.on('data', responseDecoder(id, message => {
      try { finish(null, validateIdentity(message)) } catch (error) { finish(error) }
    }))
    timer = setTimeout(() => finish(new Error('No compatible firmware responded. Install firmware 1.1.2 or later with USB identification, then retry.')), timeout)
    port.open(error => {
      opening = false
      if (settled) { finishOpen?.(); return }
      if (error) { finish(error); return }
      // No explicit DTR/RTS reset. Retry hello to tolerate boards resetting on
      // port open and their initial display/SD-card setup delay.
      const send = () => port.write(JSON.stringify({ protocol: 1, id, command: 'hello' }) + '\n', error => { if (error) finish(error) })
      send(); if (!settled) retry = setInterval(send, 600)
    })
  })
}

export async function serialPorts() {
  return (await SerialPort.list()).filter(p => /^COM\d+$/.test(p.path)).map(p => ({
    port: p.path, label: `${p.path}${p.manufacturer ? ` — ${p.manufacturer}` : ''}`,
    serialNumber: p.serialNumber || '', vendorId: p.vendorId || '', productId: p.productId || ''
  }))
}

export function reconnectCandidate(original, ports) {
  const matches = ports.filter(p => original.serialNumber
    ? p.serialNumber === original.serialNumber && p.vendorId === original.vendorId
    : p.port === original.port && p.vendorId === original.vendorId && p.productId === original.productId)
  return matches.length === 1 ? matches[0] : null
}

export async function identifyAfterFlash(original, expected, { ports = serialPorts, identify = identifyPort,
  timeout = 20000, pause = ms => new Promise(resolve => setTimeout(resolve, ms)) } = {}) {
  const deadline = Date.now() + timeout
  let lastError
  do {
    await pause(750)
    const candidate = reconnectCandidate(original, await ports())
    if (!candidate) continue
    try {
      const identity = await identify(candidate.port, { timeout: 2500 })
      if (identity.board_target !== expected.board || identity.firmware_version !== expected.version ||
          (expected.hardwareId && identity.hardware_id !== expected.hardwareId)) {
        throw new Error('The responding device does not match the expected board, firmware version, or hardware ID.')
      }
      return identity
    } catch (error) {
      if (/does not match/.test(error.message)) throw error
      lastError = error
    }
  } while (Date.now() < deadline)
  throw new Error(lastError?.message || 'Board did not reconnect on a uniquely matching USB port. Refresh ports and use Identify firmware.')
}
