# Native installation and replacement

For versioned draft downloads containing all three operating-system installers,
see [Preparing a release](RELEASING.md). Publishing remains an explicit action.

GitHub's **Platform checks** workflow builds one Ubuntu 24.04 x64 `.deb` and one
macOS 15+ Apple Silicon `.dmg`. These are development artifacts, not signed public
releases. Native installer and Linux automatic generation setup checks passed
in CI, confirmed by the user. The Windows installer is unchanged.

## Choose a download

- `installer-linux-x64`: Ubuntu with automatic image/video generation setup.
- `installer-darwin-arm64`: macOS management app. MPS generation is not implemented yet.

Download and unzip the GitHub artifact. Each contains a versioned installer and
a matching `.sha256` file. Verify it using `sha256sum -c` on Ubuntu or
`shasum -a 256 -c` on macOS, followed by the checksum filename. Checksums detect
changed downloads; they do not authenticate unsigned software.

## Ubuntu: install, replace, repair, remove

Quit ESPImageServer and stop any separately started ESPImageServer server before
changing the installation. From the download directory, run the following,
replacing the quoted filename with the actual download:

```sh
sudo apt install './ESPImageServer-<version>-linux-x64.deb'
```

Launch **ESPImageServer** from the applications menu or run `espimageserver` as
your normal user. The package installs application files under
`/opt/ESPImageServer`, with a launcher and declared OS dependencies including udev.
Do not run the app with sudo. On first launch, setup checks the NVIDIA driver and automatically downloads several
GB of pinned generation components into your user profile. The startup screen
shows setup phases and package download/install details. Internet access and
sufficient free disk space are required; NVIDIA drivers are not installed by the
app. Libraries are verified before the server starts. Model weights download
separately when selected.

A failed download offers **Retry setup**. Closing the app stops setup; reopening
retries it. If no compatible GPU is available, setup explains the problem and
offers **Retry GPU check** or **Open display tools**. There is no generation opt-in.

To update, quit the app and install the newer `.deb` using the same command.
App-only updates reuse verified generation dependencies. For app-file repair:

```sh
sudo apt install --reinstall './ESPImageServer-<version>-linux-x64.deb'
```

To remove application files:

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
Generation dependencies and cached setup downloads also remain in the desktop
user profile (`generation-runtime`). Removing the app does not reclaim downloaded models or delete saved creations.
Automatic updates, migration across incompatible settings versions, signing, and
notarization are not implemented by these packages.

## Automated package checks

Native hosted jobs verify checksums, install/copy an older-version fixture, save
settings and content, upgrade to the current package, and load the preserved data
through the current backend. They also launch the upgraded desktop, reinstall at
the same version, repair a removed executable, and remove it.
External data fixtures must remain unchanged. Ubuntu exercises apt and the actual
`/opt` installation; macOS mounts the image read-only and uses an isolated
Applications directory. These checks do not establish signed-download behavior,
cross-version settings migration, or NVIDIA computation. Existing native storage
tests separately cover persisted settings and media across backend restarts.

The older-version fixture uses current source with version `0.0.1`; there are no
published older native releases in this test. The hosted upgrade checks passed
on Windows, Ubuntu, and macOS, confirmed by the user. They test replacement and preservation with the current
schema, not historical schema migrations.

Windows CI compiles the real Inno script into two isolated fixture installers,
checks registered versions and persisted app settings/content, and checks that
an existing runtime marker survives. Dependency bootstrap and the desktop binary
are lightweight fixtures; the test does not build a Windows release installer
or redownload CUDA. Linux additionally attempts an intentionally unresolvable
dependency update and verifies that its previously downloaded runtime still works.
