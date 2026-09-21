import test from 'node:test'
import assert from 'node:assert/strict'
import { nativeInstallerConfig } from './native-installer-config.mjs'

test('installer variants replace the same Linux app and declare OS serial dependency', () => {
  for (const mode of ['management']) {
    const config = nativeInstallerConfig({ target: 'linux-x64', mode, app_version: '1.2.3' }, 'linux-x64', '1.2.3')
    assert.equal(config.deb.packageName, 'espimageserver')
    assert.ok(config.deb.depends.includes('udev'))
    assert.deepEqual(config.deb.fpm, ['--deb-compression-level', '1'])
    assert.equal(config.artifactName, `ESPImageServer-1.2.3-linux-x64.\${ext}`)
  }
})
test('macOS uses an unsigned Applications disk image', () => {
  const config = nativeInstallerConfig({ target: 'darwin-arm64', mode: 'management', app_version: '1.2.3' }, 'darwin-arm64', '1.2.3')
  assert.equal(config.mac.identity, null)
  assert.equal(config.dmg.sign, false)
  assert.ok(config.dmg.contents.some(item => item.path === '/Applications'))
})
test('reject mismatched versions, targets, and unsupported modes', () => {
  const manifest = { target: 'linux-x64', mode: 'management', app_version: '1.2.3' }
  assert.throws(() => nativeInstallerConfig(manifest, 'linux-x64', '1.2.4'), /version/)
  assert.throws(() => nativeInstallerConfig({ ...manifest, mode: 'cuda' }, 'linux-x64', '1.2.3'), /base runtime/)
  assert.throws(() => nativeInstallerConfig(manifest, 'darwin-arm64', '1.2.3'), /target/)
  assert.throws(() => nativeInstallerConfig({ ...manifest, target: 'darwin-arm64', mode: 'cuda' }, 'darwin-arm64', '1.2.3'), /mode/)
})
