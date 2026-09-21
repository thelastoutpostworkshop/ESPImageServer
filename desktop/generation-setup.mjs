import { spawn } from 'node:child_process'
import path from 'node:path'

export class GenerationSetup {
  constructor({ spawnProcess = spawn, signalGroup = (pid, signal) => process.kill(-pid, signal), onStatus = () => {}, onLog = () => {} } = {}) {
    Object.assign(this, { spawnProcess, signalGroup, onStatus, onLog })
    this.child = null
  }
  start(runtime, storage) {
    if (this.child) throw new Error('Generation setup is already running')
    this.completion = new Promise((resolve, reject) => {
      const child = this.spawnProcess(runtime.pythonPath, ['-I', '-u',
        path.join(runtime.projectRoot, 'setup/linux-generation-setup.py'), runtime.projectRoot, storage],
      { detached: true, stdio: ['ignore', 'pipe', 'pipe'], env: process.env })
      this.child = child
      let buffer = '', result, failure
      child.stdout.on('data', chunk => {
        buffer += chunk.toString()
        const lines = buffer.split('\n'); buffer = lines.pop()
        for (const line of lines) {
          try {
            const event = JSON.parse(line)
            if (event.kind === 'status') this.onStatus(event.title, event.detail)
            else if (event.kind === 'log') this.onLog(event.text + '\n')
            else if (event.kind === 'error') failure = event.detail
            else if (['ready', 'unsupported'].includes(event.kind)) result = event
          } catch { this.onLog(line + '\n') }
        }
      })
      child.stderr.on('data', this.onLog)
      child.once('error', error => { this.child = null; reject(error) })
      child.once('close', code => {
        this.child = null
        if (code === 0 && result) resolve(result)
        else reject(new Error(failure || 'Generation setup stopped before it completed. Retry to continue.'))
      })
    })
    return this.completion
  }
  async stop() {
    const child = this.child
    if (!child) return
    try { this.signalGroup(child.pid, 'SIGTERM') } catch { child.kill() }
    const timer = setTimeout(() => { try { this.signalGroup(child.pid, 'SIGKILL') } catch {} }, 3000)
    try { await this.completion } catch {} finally { clearTimeout(timer) }
  }
}
