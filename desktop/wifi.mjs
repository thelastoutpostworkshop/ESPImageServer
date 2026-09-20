import { isSerialPortPath, requireDetectedPort } from './serial-ports.mjs'
import { randomUUID } from 'node:crypto'
import { SerialPort } from 'serialport'
import { responseDecoder, validateIdentity } from './identification.mjs'

const errors = {
  confirmation_required: 'Confirm Forget Wi-Fi for the selected USB board before continuing.',
  forget_failed: 'Wi-Fi removal could not be fully verified. Identify the board again to check its saved settings before retrying.',
  initialization_failed: 'The board could not initialize Wi-Fi safely. Restart it and retry.',
  busy: 'The board is already scanning or connecting. Cancel it and retry.',
  invalid_credentials: 'Enter an SSID of 1–32 UTF-8 bytes and a valid password.',
  identity_mismatch: 'The USB device changed. Identify the board again.',
  unsupported: 'Install firmware with USB Wi-Fi setup support.',
  scan_failed: 'The network scan failed. Retry with the board near your router.',
  network_not_found: 'The board could not find the network. Check its name, range, and 2.4 GHz availability.',
  authentication_failed: 'The router rejected authentication or the handshake timed out. Check the password and security mode.',
  ip_timeout: 'The board joined Wi-Fi but did not obtain an IP address. Check router DHCP settings.',
  connection_failed: 'The connection timed out. Check the network, password, signal, and router settings.',
  storage_failed: 'The board could not save the credentials. Previous settings are retained; retry.',
  host_disconnected: 'USB setup stopped responding. Previous settings were restored. Reconnect and retry.'
}
const stages = ['idle', 'scanning', 'scan_complete', 'connecting', 'obtaining_ip', 'connected', 'cancelled', 'failed', 'forgotten']
const errorText = code => typeof code === 'string' && Object.hasOwn(errors, code) ? errors[code] : 'Invalid USB Wi-Fi response.'
export function validateCredentials({ ssid, password, auth } = {}) {
  if (typeof ssid !== 'string' || !ssid.length || Buffer.byteLength(ssid, 'utf8') > 32 || ssid.includes('\0') ||
      typeof password !== 'string' || !['open', 'personal'].includes(auth) ||
      (auth === 'open' ? password !== '' : !(/^[\x20-\x7e]{8,63}$/.test(password) || /^[a-f0-9]{64}$/i.test(password)))) {
    throw new Error(errors.invalid_credentials)
  }
  return { ssid, password, auth }
}
export function validateWifi(message) {
  if (message?.protocol !== 1 || message.ok !== true) throw new Error(errorText(message?.error))
  const r = message.result
  if (!r || !stages.includes(r.wifi_state) || typeof r.wifi_configured !== 'boolean' ||
      typeof r.wifi_connected !== 'boolean' || typeof r.ip !== 'string' ||
      !/^(?:\d{1,3}\.){3}\d{1,3}$|^$/.test(r.ip) || !Array.isArray(r.networks) || r.networks.length > 20 ||
      typeof r.wifi_error !== 'string') throw new Error('Invalid USB Wi-Fi status.')
  if (r.ip && r.ip.split('.').some(part => Number(part) > 255)) throw new Error('Invalid USB IP address.')
  if (r.wifi_state === 'connected' && (!r.wifi_configured || !r.wifi_connected || !r.ip || r.ip === '0.0.0.0')) {
    throw new Error('Firmware did not confirm a saved connection with an IP address.')
  }
  if (r.wifi_state === 'forgotten' && (r.wifi_configured || r.wifi_connected || r.ip)) throw new Error('Firmware did not confirm Wi-Fi removal.')
  const networks = r.networks.map(n => {
    if (!n || typeof n.ssid !== 'string' || Buffer.byteLength(n.ssid) > 32 || n.ssid.includes('\0') ||
        !Number.isInteger(n.rssi) || n.rssi < -127 || n.rssi > 0 || !['open', 'personal', 'unsupported'].includes(n.auth)) {
      throw new Error('Invalid USB network scan response.')
    }
    return { ssid: n.ssid, rssi: n.rssi, auth: n.auth }
  })
  return { stage: r.wifi_state, configured: r.wifi_configured, connected: r.wifi_connected, ip: r.ip,
    error: r.wifi_error ? errorText(r.wifi_error) : '', networks }
}

// One open connection for the whole setup operation. Credentials never go to
// logs, snapshots, exceptions, or disk. Never toggle DTR/RTS for setup.
export class WifiSerialSession {
  constructor(port, { createPort = options => new SerialPort(options), timeout = 5000 } = {}) {
    if (!isSerialPortPath(port)) throw new Error('Select a valid USB serial port.')
    this.port = createPort({ path: port, baudRate: 115200, autoOpen: false, lock: true, rtscts: false })
    this.timeout = timeout; this.pending = new Map(); this.closed = false
    this.port.on('error', () => this.fail('USB communication failed. Check the cable and close other programs using the port.'))
    this.port.on('close', () => this.fail('USB disconnected. Reconnect and identify the board to check whether Wi-Fi was saved.'))
    this.port.on('data', responseDecoder(null, message => {
      const pending = this.pending.get(message.id)
      if (pending) { this.pending.delete(message.id); clearTimeout(pending.timer); clearInterval(pending.retry); pending.resolve(message) }
    }, 16384))
  }
  fail(message) {
    this.failure = new Error(message)
    for (const p of this.pending.values()) { clearTimeout(p.timer); clearInterval(p.retry); p.reject(this.failure) }
    this.pending.clear()
  }
  async open() {
    // SerialPort open itself has no cancellable API. Keep the shared operation
    // lock until its callback arrives, then close if the deadline elapsed.
    await new Promise((resolve, reject) => {
      let expired = false
      const timer = setTimeout(() => { expired = true }, this.timeout)
      this.port.open(error => {
        clearTimeout(timer)
        if (error || expired || this.failure) reject(new Error('Cannot open the USB port. Close Serial Monitor, refresh ports, and retry.'))
        else resolve()
      })
    })
  }
  request(command, payload = {}) {
    if (this.failure || this.closed) return Promise.reject(this.failure || new Error('USB connection is closed.'))
    return new Promise((resolve, reject) => {
      const id = randomUUID()
      let retry
      const timer = setTimeout(() => {
        clearInterval(retry); this.pending.delete(id); reject(new Error('USB response timed out. Reconnect and identify the board before retrying.'))
      }, this.timeout)
      const send = () => this.port.write(JSON.stringify({ ...payload, protocol: 1, id, command }) + '\n', error => {
        if (error) this.fail('USB write failed. Reconnect and retry.')
      })
      // Only hello is repeated, never a scan/connect mutation. Boards may reset
      // when their driver opens the port even without an explicit reset toggle.
      if (command === 'hello') retry = setInterval(send, 600)
      this.pending.set(id, { resolve, reject, timer, retry })
      send()
    })
  }
  async close() {
    this.closed = true
    this.fail('USB connection closed.')
    if (this.port.isOpen) await new Promise((resolve, reject) => this.port.close(error => error
      ? reject(new Error('Could not release the USB port. Reconnect the board before retrying.')) : resolve()))
  }
}

export class WifiSetup {
  constructor(installer, { session = port => new WifiSerialSession(port), pause = ms => new Promise(r => setTimeout(r, ms)) } = {}) {
    this.installer = installer; this.session = session; this.pause = pause
  }
  start(request = {}) {
    const { port, hardwareId, action } = request
    if (this.installer.state.busy) throw new Error('Wait for the current USB operation.')
    const identity = this.installer.state.identity
    if (!identity || identity.port !== port || identity.hardware_id !== hardwareId || !isSerialPortPath(port)) {
      throw new Error('Identify the selected board before Wi-Fi setup.')
    }
    if (!['scan', 'connect', 'forget'].includes(action)) throw new Error('Invalid Wi-Fi setup action.')
    if (action === 'forget' && request.confirm !== true) throw new Error(errors.confirmation_required)
    const credentials = action === 'connect' ? validateCredentials(request) : {}
    this.cancelled = false; this.running = true
    this.installer.state.busy = true
    this.installer.state.wifi = { stage: 'opening', port, hardwareId, error: '', networks: [], connected: false }
    this.completion = this.run(port, hardwareId, action, credentials).catch(error => {
      this.installer.state.wifi = { ...this.installer.state.wifi, stage: 'failed', error: error.message }
    }).finally(() => { this.running = false; this.installer.state.busy = false })
    return this.installer.snapshot()
  }
  cancel() { if (this.running) this.cancelled = true; return this.installer.snapshot() }
  async run(port, hardwareId, action, credentials) {
    requireDetectedPort(port, await this.installer.ports())
    const session = this.session(port)
    let commandStarted = false
    try {
      await session.open()
      const identity = validateIdentity(await session.request('hello'))
      if (identity.hardware_id !== hardwareId) throw new Error(errors.identity_mismatch)
      const required = action === 'forget' ? ['wifi_forget'] : ['wifi_scan', 'wifi_connect', 'wifi_cancel', 'wifi_status']
      if (!required.every(c => identity.capabilities.includes(c))) throw new Error(action === 'forget' ? 'Install firmware 1.1.4 or later to forget Wi-Fi over USB.' : errors.unsupported)
      if (this.cancelled) { this.installer.state.wifi.stage = 'cancelled'; return }
      const target = { hardware_id: hardwareId }
      commandStarted = true
      const response = await session.request({ scan: 'wifi_scan', connect: 'wifi_connect', forget: 'wifi_forget' }[action],
        { ...target, ...credentials, ...(action === 'forget' ? { confirm: true } : {}) })
      credentials.password = ''; credentials.ssid = ''
      let status = validateWifi(response)
      const deadline = Date.now() + 40000
      for (;;) {
        this.installer.state.wifi = { ...status, port, hardwareId }
        if (['scan_complete', 'connected', 'cancelled', 'failed', 'forgotten'].includes(status.stage)) break
        if (Date.now() > deadline) throw new Error('Wi-Fi setup timed out. Previous settings will be restored; identify the board and retry.')
        await this.pause(500)
        status = validateWifi(await session.request(this.cancelled ? 'wifi_cancel' : 'wifi_status', target))
      }
      this.installer.state.identity = { ...identity, port, wifi_configured: status.configured, wifi_connected: status.connected }
    } catch (error) {
      this.installer.state.identity = null
      this.installer.state.identityError = error.message
      if (commandStarted) {
        try { await session.request('wifi_cancel', { hardware_id: hardwareId }) } catch { /* firmware watchdog also cancels abandoned work */ }
      }
      throw error
    } finally {
      credentials.password = ''; credentials.ssid = ''
      await session.close()
    }
  }
}
