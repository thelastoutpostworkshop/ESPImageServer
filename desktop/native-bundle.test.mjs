import test from 'node:test'
import assert from 'node:assert/strict'
import { nativeBundleVariant } from './native-bundle.mjs'

test('CUDA and management bundles use separate build directories', () => {
  assert.deepEqual(nativeBundleVariant({ target: 'linux-x64', mode: 'cuda' }, 'linux-x64', true),
    { output: 'native-cuda', consumeBackend: true })
  for (const target of ['linux-x64', 'darwin-arm64']) {
    assert.deepEqual(nativeBundleVariant({ target, mode: 'management' }, target),
      { output: 'native', consumeBackend: false })
  }
})
test('wrong architecture, macOS CUDA, and unknown modes are rejected', () => {
  assert.throws(() => nativeBundleVariant({ target: 'linux-x64', mode: 'cuda' }, 'darwin-arm64'), /target/)
  assert.throws(() => nativeBundleVariant({ target: 'darwin-arm64', mode: 'cuda' }, 'darwin-arm64'), /mode/)
  assert.throws(() => nativeBundleVariant({ target: 'linux-x64', mode: 'other' }, 'linux-x64'), /mode/)
  assert.throws(() => nativeBundleVariant({ target: 'linux-x64', mode: 'management' }, 'linux-x64', true), /consumption/)
})
