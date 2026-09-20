import { build, Platform, Arch } from 'electron-builder'
import { readFile, mkdir, writeFile } from 'node:fs/promises'
import { createReadStream } from 'node:fs'
import { createHash } from 'node:crypto'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { nativeInstallerConfig } from './native-installer-config.mjs'

const desktop = path.dirname(fileURLToPath(import.meta.url))
const target = `${process.platform}-${process.arch}`
if (!['linux-x64', 'darwin-arm64'].includes(target)) throw new Error('Build installers on their supported native host')
if (!process.argv[2]) throw new Error('Provide the tested desktop bundle directory')
const source = path.resolve(process.argv[2])
const mac = process.platform === 'darwin'
const resources = path.join(source, mac ? 'ESPImageServer.app/Contents/Resources' : 'resources')
const manifest = JSON.parse(await readFile(path.join(resources, 'backend/runtime-manifest.json'), 'utf8'))
const project = await readFile(path.join(desktop, '../pyproject.toml'), 'utf8')
const version = project.split('[project]')[1]?.split(/^\[/m)[0]?.match(/^version\s*=\s*"([^"]+)"/m)?.[1]
const config = nativeInstallerConfig(manifest, target, version)
const output = path.join(desktop, 'release', manifest.mode === 'cuda' ? 'installers-cuda' : 'installers')
await mkdir(output) // Refuse to mix fresh results with stale installers.
const pkg = JSON.parse(await readFile(path.join(desktop, 'package.json'), 'utf8'))
const artifacts = await build({ projectDir: desktop, publish: 'never',
  prepackaged: mac ? path.join(source, 'ESPImageServer.app') : source,
  targets: (mac ? Platform.MAC : Platform.LINUX).createTarget(mac ? 'dmg' : 'deb', mac ? Arch.arm64 : Arch.x64),
  config: { ...pkg.build, ...config, directories: { output } }
})
const packages = artifacts.filter(file => file.endsWith(mac ? '.dmg' : '.deb'))
if (packages.length !== 1) throw new Error('Expected exactly one native installer')
for (const file of packages) {
  const hash = createHash('sha256')
  for await (const chunk of createReadStream(file)) hash.update(chunk)
  await writeFile(`${file}.sha256`, `${hash.digest('hex')}  ${path.basename(file)}\n`)
}
