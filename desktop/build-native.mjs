import { build, Platform, Arch } from 'electron-builder'
import { readFile, access, rename } from 'node:fs/promises'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { nativeBundleVariant } from './native-bundle.mjs'

const desktop = path.dirname(fileURLToPath(import.meta.url))
const target = `${process.platform}-${process.arch}`
const targets = { 'linux-x64': ['linux-amd64', Platform.LINUX, Arch.x64],
  'darwin-arm64': ['macos-arm64', Platform.MAC, Arch.arm64] }
if (!targets[target]) throw new Error(`Native build does not support ${target}`)
const [tool, platform, arch] = targets[target]
const backend = path.resolve(process.argv[2] || '../dist/native-backend')
const manifest = JSON.parse(await readFile(path.join(backend, 'runtime-manifest.json'), 'utf8'))
const variant = nativeBundleVariant(manifest, target, process.argv.includes('--consume-backend'))
await access(path.join(backend, '.venv/bin/python'))
await access(path.join(desktop, 'tools/esptool', `esptool-${tool}`, 'esptool'))
const pkg = JSON.parse(await readFile(path.join(desktop, 'package.json'), 'utf8'))
await build({ projectDir: desktop, targets: platform.createTarget('dir', arch), config: {
  ...pkg.build,
  directories: { output: path.join(desktop, 'release', variant.output) },
  extraMetadata: { version: manifest.app_version },
  extraResources: [
    ...(variant.consumeBackend ? [] : [{ from: backend, to: 'backend', filter: ['**/*'] }]),
    { from: path.join(desktop, 'tools/esptool', `esptool-${tool}`), to: `tools/esptool/esptool-${tool}`, filter: ['**/*'] }
  ],
  // CUDA libraries are large. Native CI can explicitly move its already-verified
  // backend into the bundle to avoid keeping two full copies on the runner.
  afterPack: variant.consumeBackend ? async context => {
    await rename(backend, path.join(context.appOutDir, 'resources/backend'))
  } : undefined,
  linux: { executableName: 'espimageserver', category: 'Graphics' },
  mac: { identity: null, minimumSystemVersion: '15.0', category: 'public.app-category.graphics-design' }
} })
