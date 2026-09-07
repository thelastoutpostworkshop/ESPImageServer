# Local firmware packages

After manually compiling the selected ESPImageDisplay target/profile, copy all
four binaries referenced by `flash_args`, that file, and `build.options.json`
into a separate folder. Use a fresh credential-free build. The packaging script
does not inspect binaries for passwords or prove their application identity.

From the ESPImageServer repository, run:

```powershell
& .\scripts\package-firmware.ps1 `
  -PackageDirectory 'C:\Users\charles\Desktop\ESPImage Firmwares' `
  -BoardTarget JC4827W543 `
  -FirmwareVersion 1.1.1
```

Set the board/version to those actually compiled. Accepted board targets are
`JC4827W543`, `ST7701_320X820`, `ESP32_C6_LCD_147`, and
`CHEAP_YELLOW_DISPLAY`. The script checks the chip family against the board
selection, but two boards can share a chip. Board and version remain explicit
publisher declarations until post-flash identification is implemented.

The script writes (or regenerates) `manifest.json` in the supplied folder after
validation. It records schema version 1, first-install package type, declared
board/version, FQBN, chip, flash settings, and each segment's role, filename,
offset, size, and SHA-256 hash. Offsets come from `flash_args`, not assumptions.
Keep each board/version in its own folder. Paths in the manifest are relative
filenames; absolute build paths and arbitrary compiler flags are not copied.

Supported input is a flat Arduino export: explicit flash mode/frequency/size,
one bootloader, one partition table, `boot_app0.bin`, and one `.ino.bin`
application. Unsupported layouts fail rather than being guessed. Missing/empty
files, unsafe paths, duplicate files, overlapping erase sectors, and writes
outside flash capacity are rejected before an existing manifest is replaced.

Checksums detect changed files; they do not authenticate a publisher. This
script prepares first-install packages, not a settings-preserving update plan.
It does not validate partition-table contents or the chip encoded inside each
binary. The future flashing service must revalidate the manifest and files,
check the physical device and image compatibility, and verify the write/boot.
Treat local packages as trusted publisher inputs, not as arbitrary commands.

No compilation, flashing, firmware download, or installer build is performed.
Only `manifest.json` changes in the input folder. The flashing screen remains
a separate implementation step.

Run the hardware-free packaging checks with:

```powershell
& .\scripts\test-package-firmware.ps1
```
