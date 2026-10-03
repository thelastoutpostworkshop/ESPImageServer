import { readFile, writeFile, readdir, realpath, lstat } from 'node:fs/promises'
import path from 'node:path'
import { validatePackage } from './firmware.mjs'

// Only scan the selected root, board folders, and version folders. Never follow
// links or crawl arbitrary disk contents. Package selection validates again.
export class FirmwareLibrary {
  constructor(settingsFile, validate = validatePackage) {
    this.settingsFile = settingsFile; this.validate = validate
    this.state = { directory: '', checkedAt: null, packages: [], issues: [], error: '' }
  }
  snapshot() { return structuredClone(this.state) }
  async load() {
    try {
      const saved = JSON.parse(await readFile(this.settingsFile, 'utf8'))
      if (typeof saved.directory === 'string') this.state.directory = saved.directory
    } catch { /* no saved library yet */ }
    return this.scan()
  }
  async choose(directory) {
    const resolved = await realpath(directory)
    if (!(await lstat(resolved)).isDirectory()) throw new Error('Choose a firmware library folder.')
    await writeFile(this.settingsFile, JSON.stringify({ directory: resolved }), 'utf8')
    this.state.directory = resolved
    return this.scan()
  }
  async scan() {
    const state = { directory: this.state.directory, checkedAt: null, packages: [], issues: [], error: '' }
    if (!state.directory) { this.state = state; return this.snapshot() }
    let visited = 0
    const walk = async (directory, depth) => {
      if (++visited > 512) throw new Error('This library is too large. Choose a folder containing only firmware packages.')
      const entries = await readdir(directory, { withFileTypes: true })
      if (entries.some(e => e.name === 'manifest.json' && e.isFile())) {
        try {
          const { manifest: m, directory: root } = await this.validate(directory)
          state.packages.push({ directory: root, board: m.board_target, version: m.firmware_version,
            notes: typeof m.release_notes === 'string' ? m.release_notes.slice(0, 2000) : '' })
        } catch (error) { state.issues.push({ folder: path.relative(state.directory, directory) || '.', message: error.message }) }
      }
      if (depth < 2) for (const entry of entries) {
        if (entry.isDirectory() && !entry.isSymbolicLink()) await walk(path.join(directory, entry.name), depth + 1)
      }
    }
    try { await walk(state.directory, 0); state.checkedAt = new Date().toISOString() }
    catch (error) { state.error = `Could not check the firmware library: ${error.message}`; state.packages = [] }
    this.state = state
    return this.snapshot()
  }
  async select(directory, installer) {
    const pkg = this.state.packages.find(p => p.directory === directory)
    const identity = installer.state.identity
    if (!pkg || !identity || identity.port !== installer.state.selectedPort || identity.board_target !== pkg.board) {
      throw new Error('Identify this board again, then choose a matching firmware package.')
    }
    const target = installer.captureInstallTarget(identity.port, pkg.board)
    await installer.select(pkg.directory, target)
    // The manifest may have changed since the library was checked.
    if (installer.state.package.board !== pkg.board || installer.state.package.version !== pkg.version) {
      installer.selected = null; installer.state.package = null
      throw new Error('This package changed. Check the firmware library again.')
    }
    return installer.snapshot()
  }
}
