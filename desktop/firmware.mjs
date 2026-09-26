import { isSerialPortPath, requireDetectedPort, serialPorts } from './serial-ports.mjs'
import { createHash } from 'node:crypto'
import { lstat, readFile, realpath, mkdtemp, writeFile, rm } from 'node:fs/promises'
import path from 'node:path'
import os from 'node:os'
import { spawn } from 'node:child_process'

export const boards = {
  JC4827W543: 'esp32s3', ST7701_320X820: 'esp32s3',
  ESP32_C6_LCD_147: 'esp32c6', CHEAP_YELLOW_DISPLAY: 'esp32',
  ESP32_S3_AMOLED_143: 'esp32s3'
}
const hash = data => createHash('sha256').update(data).digest('hex')
const requireValue = (ok, message) => { if (!ok) throw new Error(message) }

export async function validatePackage(directory) {
  const root = await realpath(directory)
  async function file(name, limit) {
    requireValue(typeof name === 'string' && /^[a-z0-9][a-z0-9_.-]*$/i.test(name), 'Invalid package filename.')
    const filename = path.join(root, name)
    const stat = await lstat(filename)
    requireValue(stat.isFile() && !stat.isSymbolicLink() && stat.size > 0 && stat.size <= limit, `Invalid file: ${name}`)
    requireValue(path.dirname(await realpath(filename)) === root, 'Package file escapes its folder.')
    return readFile(filename)
  }
  const raw = await file('manifest.json', 64 * 1024)
  const m = JSON.parse(raw.toString('utf8').replace(/^\uFEFF/, ''))
  requireValue(m.schema_version === 1 && m.package_type === 'esp-image-display-firmware' && m.installation_type === 'first_install', 'Unsupported firmware manifest.')
  requireValue(Object.hasOwn(boards, m.board_target) && boards[m.board_target] === m.chip, 'Board and chip do not match.')
  requireValue(typeof m.firmware_version === 'string' && /^\d+\.\d+\.\d+$/i.test(m.firmware_version), 'Invalid firmware version.')
  requireValue(['dio', 'dout', 'qio', 'qout'].includes(m.flash?.mode) && ['20m', '26m', '40m', '80m', '120m'].includes(m.flash?.frequency), 'Unsupported flash settings.')
  requireValue([1, 2, 4, 8, 16, 32, 64, 128].map(n => n * 1048576).includes(m.flash.size_bytes), 'Invalid flash capacity.')
  requireValue(Array.isArray(m.segments) && m.segments.length === 4, 'First installation requires four binary segments.')
  const roles = new Set(), names = new Set(), segments = []
  for (const s of m.segments) {
    requireValue(['bootloader', 'partition_table', 'ota_data', 'application'].includes(s.role) && !roles.has(s.role), 'Missing or duplicate segment role.')
    requireValue(typeof s.offset === 'string' && /^0x[0-9a-f]{1,8}$/i.test(s.offset), 'Invalid flash offset.')
    const offset = Number(s.offset)
    requireValue(Number.isSafeInteger(s.size_bytes) && s.size_bytes > 0 && offset % 4096 === 0 && offset + s.size_bytes <= m.flash.size_bytes, 'Flash segment exceeds capacity or is unaligned.')
    requireValue(typeof s.sha256 === 'string' && /^[a-f0-9]{64}$/.test(s.sha256), 'Invalid SHA-256 checksum.')
    requireValue(typeof s.file === 'string' && /\.bin$/i.test(s.file) && !names.has(s.file.toLowerCase()), 'Invalid or repeated binary filename.')
    const data = await file(s.file, m.flash.size_bytes)
    requireValue(data.length === s.size_bytes && hash(data) === s.sha256, `Checksum or size mismatch: ${s.file}`)
    if (s.role === 'application' || s.role === 'bootloader') {
      const chipIds = { esp32: 0, esp32s3: 9, esp32c6: 13 }
      requireValue(data.length >= 24 && data[0] === 0xe9 && data.readUInt16LE(12) === chipIds[m.chip], `Invalid or incompatible ESP image: ${s.file}`)
    }
    roles.add(s.role); names.add(s.file.toLowerCase())
    segments.push({ ...s, offset, data })
  }
  segments.sort((a, b) => a.offset - b.offset)
  let end = 0
  for (const s of segments) {
    requireValue(s.offset >= end, 'Flash segments overlap, including erased sectors.')
    end = s.offset + Math.ceil(s.size_bytes / 4096) * 4096
  }
  // First milestone supports the normal Arduino layout. Protect the NVS gap
  // and verify the application lies within its actual partition, not padding.
  const byRole = Object.fromEntries(segments.map(s => [s.role, s]))
  requireValue(byRole.bootloader.offset === (m.chip === 'esp32' ? 0x1000 : 0) &&
    byRole.partition_table.offset === 0x8000 && byRole.ota_data.offset === 0xe000 &&
    byRole.application.offset === 0x10000, 'Unsupported Arduino partition layout.')
  requireValue(byRole.partition_table.size_bytes <= 4096 && byRole.ota_data.size_bytes <= 8192,
    'Partition metadata would overwrite reserved settings space.')
  const table = byRole.partition_table.data
  let applicationFits = false
  for (let i = 0; i + 32 <= table.length && table.readUInt16LE(i) === 0x50aa; i += 32) {
    if (table[i + 2] === 0 && table.readUInt32LE(i + 4) === byRole.application.offset &&
      table.readUInt32LE(i + 8) >= byRole.application.size_bytes &&
      table.readUInt32LE(i + 4) + table.readUInt32LE(i + 8) <= m.flash.size_bytes) applicationFits = true
  }
  requireValue(applicationFits, 'Application does not fit the supplied partition table.')
  return { manifest: m, segments, fingerprint: hash(raw), directory: root }
}

export function parseProbe(output, expectedChip, requiredBytes) {
  const description = output.match(/(?:Chip (?:is|type:)\s*|Detecting chip type\.\.\.\s*)(ESP32[^\s(]*)/i)?.[1].toUpperCase()
  const chip = /^ESP32-S3(?:$|[-(])/.test(description) ? 'esp32s3'
    : /^ESP32-C6(?:FH4)?(?:$|[-(])/.test(description) ? 'esp32c6'
      : /^ESP32(?:$|-(?:D0WD|U4WD|S0WD|PICO))/.test(description) ? 'esp32' : null
  const size = output.match(/Detected flash size:\s*(\d+)\s*MB/i)
  const chipNames = { esp32: 'ESP32', esp32s3: 'ESP32-S3', esp32c6: 'ESP32-C6' }
  requireValue(chip === expectedChip, `Detected chip ${description || 'unknown'} does not match this package (${chipNames[expectedChip] || expectedChip}). Check the USB port and firmware package.`)
  requireValue(size && Number(size[1]) * 1048576 >= requiredBytes, 'Could not verify sufficient flash capacity on this board.')
  return { chip, flashBytes: Number(size[1]) * 1048576 }
}

export function writeArguments(m, port, segments, baud = 460800) {
  return ['--chip', m.chip, '--port', port, '--baud', String(baud), '--before', 'default-reset', '--after', 'hard-reset',
    'write-flash', '--flash-mode', m.flash.mode, '--flash-freq', m.flash.frequency,
    '--flash-size', `${m.flash.size_bytes / 1048576}MB`, ...segments.flatMap(s => [`0x${s.offset.toString(16)}`, s.file])]
}

export function runProcess(executable, args, { cwd, timeout = 120000, onOutput = () => {}, onChild = () => {} } = {}) {
  return new Promise((resolve, reject) => {
    const child = spawn(executable, args, { cwd, windowsHide: true, shell: false, stdio: ['ignore', 'pipe', 'pipe'], env: { ...process.env, NO_COLOR: '1', TERM: 'dumb' } })
    onChild(child)
    let output = '', timedOut = false
    const timer = setTimeout(() => {
      timedOut = true
      // The Windows standalone esptool launcher can own a child process. Keep
      // the job locked until the whole tree exits and releases the serial port.
      if (process.platform === 'win32' && child.pid) {
        const killer = spawn('taskkill.exe', ['/PID', String(child.pid), '/T', '/F'], { windowsHide: true, shell: false, stdio: 'ignore' })
        killer.once('error', () => child.kill())
      } else child.kill()
    }, timeout)
    const receive = chunk => {
      const text = chunk.toString().replace(/\x1b\[[0-?]*[ -/]*[@-~]/g, '')
      output = (output + text).slice(-256000)
      onOutput(text)
    }
    child.stdout.on('data', receive); child.stderr.on('data', receive)
    child.once('error', error => { clearTimeout(timer); reject(error) })
    child.once('close', code => {
      clearTimeout(timer)
      if (timedOut) reject(new Error('Device operation timed out. Reconnect the board and retry.'))
      else if (code !== 0) reject(new Error(`esptool failed (${code ?? 'interrupted'}). Check the log, USB cable, and whether another app holds the port.`))
      else resolve(output)
    })
  })
}

export const listPorts = serialPorts

export class FirmwareInstaller {
  constructor(toolPath, { run = runProcess, ports = listPorts, identify = null, reconnect = null } = {}) {
    this.toolPath = toolPath; this.run = run; this.ports = ports
    this.identify = identify; this.reconnect = reconnect
    this.state = { busy: false, stage: 'idle', log: '', package: null, error: '' }
  }
  snapshot() { return structuredClone(this.state) }
  selectPort(port) {
    requireValue(!this.state.busy && (port === '' || isSerialPortPath(port)), 'Wait for USB work to finish and select a valid port.')
    if (port !== '') requireDetectedPort(port, this.knownPorts)
    this.state.selectedPort = port
    this.state.identity = null; this.state.wifi = null; this.state.identityError = ''
    this.identityPort = null
    return this.snapshot()
  }
  async refreshPorts() {
    const ports = await this.ports()
    const identity = this.state.identity
    if (identity && !this.state.busy) {
      const current = ports.find(p => p.port === identity.port)
      const changed = this.identityPort && ['serialNumber', 'vendorId', 'productId'].some(key =>
        (this.identityPort[key] || '') !== (current?.[key] || ''))
      if (!current || changed) {
        this.state.identity = null; this.state.wifi = null
        this.state.identityError = 'The USB device was disconnected or changed. Select its port and identify it again.'
        this.identityPort = null
      } else this.identityPort = { ...current }
    }
    this.knownPorts = ports
    return ports
  }
  async identifyFirmware(port) {
    requireValue(!this.state.busy && this.identify && isSerialPortPath(port), 'Select an available port and wait for the current operation.')
    this.state.busy = true; this.state.identityError = ''; this.state.identity = null; this.state.wifi = null
    try {
      const detected = requireDetectedPort(port, await this.ports())
      this.state.identity = await this.identify(port)
      this.state.selectedPort = port
      this.identityPort = { ...detected }
    }
    catch (error) { this.state.identityError = error.message }
    finally { this.state.busy = false }
    return this.snapshot()
  }
  async refreshIdentity(port) {
    requireValue(!this.state.busy && this.state.identity?.port === port && this.state.selectedPort === port,
      'Identify the selected display first.')
    const previous = this.state.identity
    this.state.busy = true
    try {
      requireDetectedPort(port, await this.ports())
      const identity = await this.identify(port)
      requireValue(identity.hardware_id === previous.hardware_id, 'The USB display changed. Identify it again.')
      this.state.identity = identity; this.state.identityError = ''
    } catch (error) {
      this.state.identity = null; this.state.wifi = null; this.state.identityError = error.message
    } finally { this.state.busy = false }
    return this.snapshot()
  }
  async select(directory) {
    requireValue(!this.state.busy, 'A firmware operation is already running.')
    this.state = { ...this.state, busy: true, package: null, error: '', stage: 'validating' }
    this.selected = null
    try {
      const pkg = await validatePackage(directory)
      this.selected = { directory: pkg.directory, fingerprint: pkg.fingerprint }
      this.state.package = { board: pkg.manifest.board_target, version: pkg.manifest.firmware_version, chip: pkg.manifest.chip,
        flashBytes: pkg.manifest.flash.size_bytes, directory: pkg.directory, files: pkg.manifest.segments.map(s => ({ file: s.file, size: s.size_bytes })) }
      this.state.stage = 'ready'; this.state.log = ''
      return this.snapshot()
    } catch (e) { this.state.stage = 'failed'; this.state.error = e.message; throw e }
    finally { this.state.busy = false }
  }
  start(port, board, baud) {
    requireValue(!this.state.busy && this.selected, 'Choose a valid package first; only one installation can run.')
    requireValue(isSerialPortPath(port) && board === this.state.package.board && [115200, 460800].includes(baud), 'Confirm the matching physical board, port, and speed.')
    this.expectedHardwareId = this.state.identity?.port === port ? this.state.identity.hardware_id : undefined
    this.state = { ...this.state, busy: true, stage: 'validating', error: '', log: '', port, selectedPort: port, identity: null, identityError: '', wifi: null }
    this.completion = this.install(port, baud).catch(e => {
      this.state.stage = 'failed'; this.state.error = e.message
    }).finally(() => { this.state.busy = false; this.child = null })
    return this.snapshot()
  }
  async install(port, baud) {
    let staged
    try {
      const pkg = await validatePackage(this.selected.directory)
      requireValue(pkg.fingerprint === this.selected.fingerprint, 'Package changed since selection. Choose it again.')
      const originalPort = requireDetectedPort(port, await this.ports())
      // Flash an immutable snapshot of verified bytes, not mutable source paths.
      staged = await mkdtemp(path.join(os.tmpdir(), 'espimage-flash-'))
      for (const s of pkg.segments) await writeFile(path.join(staged, s.file), s.data)
      const options = { cwd: staged, onChild: child => { this.child = child }, onOutput: text => {
        this.state.log = (this.state.log + text).slice(-32000)
        if (/Writing at|Wrote \d|Hash of data verified/i.test(text)) this.state.stage = 'writing_and_verifying'
        if (/Hard resetting/i.test(text) && this.state.stage === 'writing_and_verifying') this.state.stage = 'restarting'
      } }
      this.state.stage = 'connecting'
      const probe = await this.run(this.toolPath, ['--chip', pkg.manifest.chip, '--port', port, '--baud', '115200', '--before', 'default-reset', '--after', 'hard-reset', 'flash-id'], options)
      parseProbe(probe, pkg.manifest.chip, pkg.manifest.flash.size_bytes)
      this.state.stage = 'writing_and_verifying'
      const output = await this.run(this.toolPath, writeArguments(pkg.manifest, port, pkg.segments, baud), { ...options, timeout: 900000 })
      requireValue((output.match(/Hash of data verified/gi) || []).length >= pkg.segments.length, 'Write finished without all four verification results. Review the log before retrying.')
      this.state.stage = 'written'
      if (this.reconnect) {
        this.state.stage = 'identifying'
        try {
          this.state.identity = await this.reconnect(originalPort, {
            board: pkg.manifest.board_target, version: pkg.manifest.firmware_version, hardwareId: this.expectedHardwareId
          })
          this.state.selectedPort = this.state.identity.port
          this.identityPort = null
          this.state.stage = 'boot_verified'
        } catch (error) {
          this.state.stage = 'written'
          this.state.identityError = `Flash writes verified, but firmware startup was not confirmed: ${error.message}`
        }
      }
    } finally { if (staged) await rm(staged, { recursive: true, force: true }) }
  }
}
