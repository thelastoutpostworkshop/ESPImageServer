# Local firmware packages

Start with the [contributor guide](../CONTRIBUTING.md#create-a-local-firmware-package-and-manifest)
for the folder layout, required files, and script parameters.

After manually compiling the selected ESPImageDisplay target/profile, copy all
four binaries referenced by `flash_args`, that file, and `build.options.json`
into a separate folder. Use a fresh credential-free build. The packaging script
does not inspect binaries for passwords or prove their application identity.

From the ESPImageServer repository, run:

```powershell
& .\scripts\package-firmware.ps1 `
  -PackageDirectory 'C:\Users\charles\Desktop\ESPImage Firmwares\JC4827W543\1.1.2' `
  -BoardTarget JC4827W543 `
  -FirmwareVersion 1.1.2
```

Set the board/version to those actually compiled. Accepted board targets are
`JC4827W543`, `ST7701_320X820`, `ESP32_C6_LCD_147`, and
`CHEAP_YELLOW_DISPLAY`. The script checks the chip family against the board
selection, but two boards can share a chip. Board and version remain explicit
publisher declarations in the package; USB identification checks the running
firmware's board/version after flashing when supported by that firmware.

The script writes (or regenerates) `manifest.json` in the supplied folder after
validation. It records schema version 1, first-install package type, declared
board/version, FQBN, chip, flash settings, and each segment's role, filename,
offset, size, and SHA-256 hash. Offsets come from `flash_args`, not assumptions.
Keep each board/version in its own folder. Paths in the manifest are relative
filenames; absolute build paths and arbitrary compiler flags are not copied.

For ESP32-C6 and ESP32-S3, Arduino-ESP32's QIO menu preset exports `--flash-mode dio`.
The packager accepts this preset mapping and preserves the exported DIO mode;
do not edit `flash_args` or relabel the build options to make them match.

Supported input is a flat Arduino export: explicit flash mode/frequency/size,
one bootloader, one partition table, `boot_app0.bin`, and one `.ino.bin`
application. Unsupported layouts fail rather than being guessed. Missing/empty
files, unsafe paths, duplicate files, overlapping erase sectors, and writes
outside flash capacity are rejected before an existing manifest is replaced.

Checksums detect changed files; they do not authenticate a publisher. This
script prepares first-install packages, not a settings-preserving update plan.
It does not validate partition-table contents or the chip encoded inside each
binary. The desktop flashing service revalidates the manifest and files,
checks the physical chip and image compatibility, and verifies writes. Firmware
startup is reported separately through USB identification when available.
Treat local packages as trusted publisher inputs, not as arbitrary commands.

No compilation, flashing, firmware download, or installer build is performed.
Only `manifest.json` changes in the input folder. In the desktop app's
**Install firmware** screen, select this version folder, the matching physical
board, and its COM port. The app revalidates the package and checks ESP image
headers and the application partition before starting esptool. Current flashing
support is limited to the standard Arduino layout (partition table at 0x8000,
OTA data at 0xe000, application at 0x10000, and the chip's normal bootloader
offset); other layouts are rejected. No hardware flashing test is performed by
the packaging script or automated test suite.

Run the hardware-free packaging checks with:

```powershell
& .\scripts\test-package-firmware.ps1
```
