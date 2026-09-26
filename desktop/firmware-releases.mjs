import { isSerialPortPath } from './serial-ports.mjs'
import { createHash } from 'node:crypto'
import { mkdir, mkdtemp, readFile, writeFile, rm, realpath } from 'node:fs/promises'
import path from 'node:path'
import yauzl from 'yauzl'
import { boards, validatePackage } from './firmware.mjs'

export const REPOSITORY = 'thelastoutpostworkshop/ESPImageFirmware'
const API = `https://api.github.com/repos/${REPOSITORY}/releases`
const DOWNLOAD = `https://github.com/${REPOSITORY}/releases/download/`
const MAX_ZIP = 32 * 1048576, MAX_EXPANDED = 64 * 1048576
const requireValue = (ok, message) => { if (!ok) throw new Error(message) }
const hash = data => createHash('sha256').update(data).digest('hex')

function allowedURL(value) {
  const url = new URL(value)
  requireValue(url.protocol === 'https:' && !url.username && !url.password && !url.port &&
    ((url.origin === 'https://api.github.com' && url.pathname === `/repos/${REPOSITORY}/releases`) ||
     value.startsWith(DOWNLOAD) || ['release-assets.githubusercontent.com', 'objects.githubusercontent.com'].includes(url.hostname)),
  'Firmware download was redirected outside GitHub.')
  return url
}

// All requests are public and credential-free. Bound redirects, time, and bytes.
export async function downloadBytes(url, limit, { fetcher = fetch, signal, progress = () => {} } = {}) {
  const timeout = AbortSignal.timeout(120000)
  const combined = signal ? AbortSignal.any([signal, timeout]) : timeout
  for (let redirects = 0; redirects <= 4; redirects++) {
    const target = allowedURL(url)
    const response = await fetcher(target.href, { redirect: 'manual', signal: combined,
      headers: { 'User-Agent': 'ESPImageServer', Accept: target.hostname === 'api.github.com' ? 'application/vnd.github+json' : 'application/octet-stream' } })
    if ([301,302,303,307,308].includes(response.status)) {
      await response.body?.cancel()
      url = new URL(response.headers.get('location'), target).href
      continue
    }
    if (!response.ok) {
      await response.body?.cancel()
      throw new Error([403,429].includes(response.status) ? 'GitHub is limiting requests. Try again later, or use a local package.' :
        `GitHub download failed (${response.status}). Check your connection and try again.`)
    }
    const total = Number(response.headers.get('content-length')) || 0
    if (total > limit) { await response.body?.cancel(); throw new Error('Firmware download exceeds the size limit.') }
    requireValue(response.body, 'GitHub returned an empty download.')
    const chunks = []; let received = 0
    for await (const chunk of response.body) {
      combined.throwIfAborted()
      received += chunk.length
      requireValue(received <= limit, 'Firmware download exceeds the size limit.')
      chunks.push(chunk); progress(received, total)
    }
    return Buffer.concat(chunks)
  }
  throw new Error('Too many GitHub download redirects.')
}

export function releasePackages(releases) {
  requireValue(Array.isArray(releases), 'GitHub returned an invalid release list.')
  const packages = []
  for (const release of releases) {
    if (release.draft || release.prerelease || !/^v\d+\.\d+\.\d+$/i.test(release.tag_name)) continue
    const version = release.tag_name.slice(1), assets = release.assets || []
    if (!Array.isArray(assets)) continue
    const assetURL = name => `${DOWNLOAD}${encodeURIComponent(release.tag_name)}/${encodeURIComponent(name)}`
    const sums = assets.filter(a => a.name === 'SHA256SUMS.txt' && a.state === 'uploaded' && a.browser_download_url === assetURL(a.name))
    if (sums.length !== 1 || sums[0].size > 65536) continue
    for (const board of Object.keys(boards)) {
      const filename = `ESPImageDisplay-${board}-${version}.zip`
      const matching = assets.filter(a => a.name === filename && a.state === 'uploaded')
      if (matching.length !== 1) continue
      const asset = matching[0]
      if (!Number.isSafeInteger(asset.id) || asset.browser_download_url !== assetURL(filename) ||
          !Number.isSafeInteger(asset.size) || asset.size < 1 || asset.size > MAX_ZIP) continue
      packages.push({ id: String(asset.id), board, version, source: 'github',
        notes: typeof release.body === 'string' ? release.body.slice(0, 12000) : '',
        filename, url: assetURL(filename), checksumURL: assetURL('SHA256SUMS.txt'), size: asset.size,
        digest: /^sha256:[a-f0-9]{64}$/.test(asset.digest) ? asset.digest.slice(7) : null })
    }
  }
  return packages
}

export async function extractFirmwareZip(data, directory) {
  const zip = await yauzl.fromBufferPromise(data, { lazyEntries: true, strictFileNames: true, validateEntrySizes: true })
  const names = new Set(); let total = 0
  try {
    for await (const entry of zip.eachEntry()) {
      const name = entry.fileName, mode = (entry.externalFileAttributes >>> 16) & 0xf000
      requireValue(/^[a-z0-9][a-z0-9_.-]*$/i.test(name) &&
        !/^(con|prn|aux|nul|com\d|lpt\d)(\.|$)/i.test(name) &&
        (name === 'manifest.json' || name === 'LICENSE.txt' || name.endsWith('.bin')) &&
        !names.has(name.toLowerCase()) && names.size < 6 && (mode === 0 || mode === 0x8000) &&
        !(entry.generalPurposeBitFlag & 1), 'ZIP contains unsafe or unexpected files.')
      const limit = name === 'manifest.json' || name === 'LICENSE.txt' ? 65536 : 32 * 1048576
      requireValue(entry.uncompressedSize > 0 && entry.uncompressedSize <= limit && total + entry.uncompressedSize <= MAX_EXPANDED,
        'Expanded firmware exceeds the size limit.')
      names.add(name.toLowerCase())
      const stream = await zip.openReadStreamPromise(entry)
      const chunks = []; let length = 0
      for await (const chunk of stream) {
        length += chunk.length
        requireValue(length <= limit && total + length <= MAX_EXPANDED, 'Expanded firmware exceeds the size limit.')
        chunks.push(chunk)
      }
      total += length
      await writeFile(path.join(directory, name), Buffer.concat(chunks), { flag: 'wx' })
    }
    requireValue(names.has('manifest.json') && [...names].filter(n => n.endsWith('.bin')).length === 4,
      'ZIP must contain a manifest and four firmware binaries.')
  } finally { zip.close() }
}

export class FirmwareReleases {
  constructor(cacheDirectory, { download = downloadBytes, validate = validatePackage } = {}) {
    this.cacheDirectory = path.resolve(cacheDirectory); this.download = download; this.validate = validate
    this.state = { packages: [], checkedAt: null, error: '', busy: false, download: null }
    this.controller = null; this.checking = null; this.selectedDirectory = null
  }
  snapshot() { return structuredClone(this.state) }
  async check(force = false) {
    if (this.checking) return this.checking
    if (this.state.busy || (!force && this.state.checkedAt && Date.now() - Date.parse(this.state.checkedAt) < 300000)) return this.snapshot()
    this.checking = this.checkReleases().finally(() => { this.checking = null })
    return this.checking
  }
  async checkReleases() {
    try {
      const releases = []
      for (let page = 1; page <= 10; page++) {
        const data = JSON.parse((await this.download(`${API}?per_page=100&page=${page}`, 4 * 1048576)).toString('utf8'))
        requireValue(Array.isArray(data), 'GitHub returned an invalid release list.')
        releases.push(...data)
        if (data.length < 100) break
        requireValue(page < 10, 'Too many firmware releases to check. Please update the desktop app.')
      }
      this.state.packages = releasePackages(releases)
      this.state.checkedAt = new Date().toISOString(); this.state.error = ''
    } catch (error) {
      this.state.error = `Could not check GitHub firmware: ${error.message}`
      this.state.checkedAt = null; this.state.packages = []
    }
    return this.snapshot()
  }
  cancel() { this.controller?.abort(); return this.snapshot() }
  async select({ id, board, port } = {}, installer) {
    requireValue(!this.state.busy && !installer.state.busy, 'Wait for the current operation to finish.')
    const pkg = this.state.packages.find(p => p.id === id)
    requireValue(pkg && pkg.board === board && !pkg.prerelease && /^\d+\.\d+\.\d+$/.test(pkg.version), 'Choose a matching firmware release.')
    const identity = installer.state.identity, hardware = identity?.hardware_id
    const matchingBoard = () => installer.state.selectedPort === port && isSerialPortPath(port) &&
      (!installer.state.identity || (installer.state.identity.port === port && installer.state.identity.board_target === board)) &&
      (!hardware || installer.state.identity?.hardware_id === hardware)
    requireValue(matchingBoard(), 'The selected USB display changed. Check it again.')
    this.state.busy = true; this.state.download = { stage: 'downloading', received: 0, total: pkg.size }
    this.controller = new AbortController()
    const signal = this.controller.signal
    let staging
    try {
      const sums = (await this.download(pkg.checksumURL, 65536, { signal })).toString('utf8')
      const matches = sums.split(/\r?\n/).map(line => /^([a-f0-9]{64})  ([A-Za-z0-9_.+-]+)$/.exec(line))
        .filter(match => match?.[2] === pkg.filename)
      requireValue(matches.length === 1 && (!pkg.digest || pkg.digest === matches[0][1]), 'Missing or conflicting ZIP checksum.')
      const digest = matches[0][1]
      await mkdir(this.cacheDirectory, { recursive: true })
      const cache = path.join(this.cacheDirectory, `${digest}.zip`)
      let data
      try { data = await readFile(cache) } catch (error) { if (error.code !== 'ENOENT') throw error }
      if (!data || hash(data) !== digest || data.length !== pkg.size) {
        data = await this.download(pkg.url, MAX_ZIP, { signal, progress: (received, total) => {
          this.state.download = { stage: 'downloading', received, total: total || pkg.size }
        } })
      }
      signal.throwIfAborted()
      requireValue(data.length === pkg.size && hash(data) === digest, 'Firmware ZIP checksum failed. Try downloading again.')
      this.state.download = { stage: 'validating', received: data.length, total: data.length }
      staging = await mkdtemp(path.join(this.cacheDirectory, 'package-'))
      await extractFirmwareZip(data, staging)
      const checked = await this.validate(staging)
      requireValue(checked.manifest.board_target === pkg.board && checked.manifest.firmware_version === pkg.version,
        'Downloaded firmware does not match the selected board and version.')
      signal.throwIfAborted()
      requireValue(!installer.state.busy && matchingBoard(), 'The selected USB display changed. Check it again.')
      await writeFile(cache, data)
      await installer.select(staging)
      installer.state.package.source = 'github'
      // Keep only the current extracted selection; ZIPs remain cached for reuse.
      const previous = this.selectedDirectory
      this.selectedDirectory = staging
      staging = null
      if (previous) await this.removeStaging(previous)
      return installer.snapshot()
    } catch (error) {
      throw new Error(signal.aborted ? 'Download cancelled. Your display was not changed.' : error.message)
    } finally {
      try { if (staging) await this.removeStaging(staging) }
      finally { this.controller = null; this.state.busy = false; this.state.download = null }
    }
  }
  async removeStaging(directory) {
    const resolved = await realpath(directory), root = await realpath(this.cacheDirectory)
    requireValue(path.dirname(resolved) === root && path.basename(resolved).startsWith('package-'), 'Invalid download staging directory.')
    await rm(resolved, { recursive: true, force: true })
  }
}
