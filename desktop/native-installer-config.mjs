import { nativeBundleVariant } from './native-bundle.mjs'

export function nativeInstallerConfig(manifest, target, version) {
  nativeBundleVariant(manifest, target)
  if (manifest.mode !== 'management') throw new Error('Installers ship the base runtime; generation dependencies download during setup')
  if (manifest.app_version !== version || !/^\d+\.\d+\.\d+$/.test(version)) {
    throw new Error('Installer version must match pyproject.toml and the backend manifest')
  }
  return {
    artifactName: `ESPImageServer-${version}-${target}.\${ext}`,
    extraMetadata: { version, homepage: 'https://github.com/thelastoutpostworkshop/ESPImageServer' },
    linux: { executableName: 'espimageserver', category: 'Graphics' },
    deb: {
      // Both modes replace the same application; they cannot coexist in /opt.
      packageName: 'espimageserver', maintainer: 'ESPImageServer',
      compression: 'gz', recommends: [],
      // Large CUDA libraries make high gzip levels disproportionately expensive.
      fpm: ['--deb-compression-level', '1'],
      depends: ['libgtk-3-0t64', 'libnotify4', 'libnss3', 'libxss1', 'libxtst6',
        'xdg-utils', 'libatspi2.0-0t64', 'libuuid1', 'libsecret-1-0', 'libasound2t64', 'udev']
    },
    mac: { identity: null, minimumSystemVersion: '15.0', category: 'public.app-category.graphics-design' },
    dmg: { sign: false, contents: [
      { x: 130, y: 220, type: 'file' },
      { x: 410, y: 220, type: 'link', path: '/Applications' }
    ] }
  }
}
