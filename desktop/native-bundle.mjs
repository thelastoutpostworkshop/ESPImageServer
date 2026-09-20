// Build-time policy; not shipped in the desktop application.
export function nativeBundleVariant(manifest, target, consumeBackend = false) {
  if (!['linux-x64', 'darwin-arm64'].includes(target) || manifest.target !== target) {
    throw new Error('Backend target mismatch')
  }
  if (manifest.mode !== 'management' && !(manifest.mode === 'cuda' && target === 'linux-x64')) {
    throw new Error('Backend mode is unsupported for this target')
  }
  if (consumeBackend && manifest.mode !== 'cuda') throw new Error('Backend consumption is limited to CUDA builds')
  return { output: manifest.mode === 'cuda' ? 'native-cuda' : 'native', consumeBackend }
}
