# Native installation and replacement

GitHub's **Platform checks** workflow now builds Ubuntu 24.04 x64 `.deb` packages
and a macOS 15+ Apple Silicon `.dmg`. Their first hosted installation checks are
pending. These are development artifacts, not signed public releases. The Windows
installer is unchanged. See [platform scope](PLATFORMS.md) and [USB help](USB_SETUP.md).

## Choose a download

- `installer-linux-x64-cuda`: Ubuntu with NVIDIA generation dependencies.
  Generation still requires a compatible NVIDIA GPU and driver.
- `installer-linux-x64-management`: Ubuntu display, library, SD-card, and USB
  management without image/video generation dependencies.
- `installer-darwin-arm64-management`: macOS display management. Generation is
  disabled on macOS, including CPU and Apple Metal/MPS.

Download and unzip the GitHub artifact. Each contains a versioned installer and
a matching `.sha256` file. Verify it using `sha256sum -c` on Ubuntu or
`shasum -a 256 -c` on macOS, followed by the checksum filename. Checksums detect
changed downloads; they do not authenticate unsigned software.

## Ubuntu: install, replace, repair, remove

Quit ESPImageServer and stop any separately started ESPImageServer server before
changing the installation. From the download directory, run the following,
replacing the quoted filename with the actual download:

```sh
sudo apt install './ESPImageServer-<version>-linux-x64-cuda.deb'
```

Launch **ESPImageServer** from the applications menu or run `espimageserver` as
your normal user. The package installs application files under
`/opt/ESPImageServer`, with a launcher and declared OS dependencies including udev.
Do not run the app with sudo. Models are downloaded separately when selected;
the installer does not install NVIDIA drivers.

To update, install the newer `.deb` with the same command. To repair or switch
between management and CUDA at the same version, use:

```sh
sudo apt install --reinstall './ESPImageServer-<version>-linux-x64-cuda.deb'
```

Both variants have the package name `espimageserver` and replace each other;
they do not install two apps. To remove application files:

```sh
sudo apt remove espimageserver
```

## macOS: install, replace, repair, remove

Open the `.dmg` and drag **ESPImageServer.app** to **Applications**, then eject the
disk image and launch the installed app. This development package is unsigned
and not notarized, so macOS may block it. Signing/notarization remains separate
release work; do not disable system security protections.

For an update or repair, use **Quit** (Command-Q), stop any separately started
server, then replace the whole application in Applications with the copy from
the new disk image. Closing the window alone does not quit the macOS app.
To uninstall, quit and move only **ESPImageServer.app** to Trash.

## What is preserved

Package replacement and removal operate on application files. Default settings,
model caches, and the configured creation library live separately and remain on
disk. On Linux, settings/data/cache use the XDG locations documented in the app;
on macOS, application data uses `~/Library/Application Support/ESPImageServer`
and its cache uses `~/Library/Caches/ESPImageServer`. Electron also keeps its own
user profile. Explicitly configured external library/model paths are preserved.

Keep personal files outside the installation directory and `.app` bundle. Files
placed inside application files can be replaced or removed with the application.
Removing the app does not reclaim downloaded models or delete saved creations.
Automatic updates, migration across incompatible settings versions, signing, and
notarization are not implemented by these packages.

## Automated package checks

Native hosted jobs verify checksums, install/copy the package, launch the installed
app, replace it at the same version, repair a removed executable, and remove it.
External data fixtures must remain unchanged. Ubuntu exercises apt and the actual
`/opt` installation; macOS mounts the image read-only and uses an isolated
Applications directory. These checks do not establish signed-download behavior,
cross-version settings migration, or NVIDIA computation. Existing native storage
tests separately cover persisted settings and media across backend restarts.
