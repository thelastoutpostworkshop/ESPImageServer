// Test-only instrumentation: Python environment overrides are deliberately
// ignored by Windows startup. Load the smoke hook explicitly instead.
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const entry = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../ci/smoke-python/run-server.py')

export function smokePythonArguments(args, platform = process.platform) {
  return platform === 'win32' && args.at(-2) === '-m' && args.at(-1) === 'esp_image_server'
    ? [...args.slice(0, -2), entry]
    : args
}
