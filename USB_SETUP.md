# USB setup on Linux and macOS

Use **Set up display** in the desktop app on the computer connected to the board.
Native desktop bundles include esptool and serial-port bindings; Arduino and a
separate Python/esptool installation are unnecessary. GPU support is not required
for USB setup. See [native installation instructions](NATIVE_INSTALL.md).

Connect a data-capable cable to the board's documented data/programming connector.
Close Serial Monitor and other serial terminals. Refresh the port list, select
the detected port, and choose **Check display**. Refresh after reconnecting: port
names can change. The app identifies the board before selecting matching firmware;
a port name alone does not identify it.

## Ubuntu 24.04: access denied

Ports commonly appear as `/dev/ttyUSB0` or `/dev/ttyACM0`. Substitute the actual
port shown in the app:

```sh
ls -l /dev/ttyACM0
id -nG
```

If the device belongs to `dialout` and your account is not a member, run:

```sh
sudo usermod -aG dialout "$USER"
```

Log out of the desktop session and log back in, then reopen the app. Membership
grants access to serial devices owned by that group. Use the actual device group
if your system differs. Run ESPImageServer as your normal user, not through
`sudo`; do not make all serial ports world-writable.
[Espressif serial permission guidance](https://docs.espressif.com/projects/esptool/en/latest/esp32/esptool/basic-options.html)

## Ubuntu: port enumeration fails

The Linux serial library uses the system `udevadm` utility. For
`spawn udevadm ENOENT`, check its availability:

```sh
command -v udevadm
```

If Ubuntu is missing udev, install the OS package with `sudo apt install udev`.
If `/usr/bin/udevadm` exists, ensure the app's launch environment includes
`/usr/bin` in PATH. This utility is supplied by the OS, not bundled Python.

### Optional device-specific permission rule

Normal Ubuntu serial permissions usually need no custom rule. If your device has
incorrect ownership, inspect its USB parent attributes:

```sh
udevadm info --attribute-walk --name=/dev/ttyACM0
```

An administrator can create `/etc/udev/rules.d/99-espimageserver.rules` using this
template. Replace all placeholders with values from the same USB parent:

```text
SUBSYSTEM=="tty", ATTRS{idVendor}=="VENDOR_ID", ATTRS{idProduct}=="PRODUCT_ID", ATTRS{serial}=="DEVICE_SERIAL", GROUP="dialout", MODE="0660"
```

Use a unique serial value, not a wildcard. If there is no serial attribute, use
the existing group-based approach above. Run `sudo udevadm control --reload-rules`,
then unplug/reconnect. To undo the customization, remove that rule file, reload,
and reconnect. [udev rule semantics](https://github.com/systemd/systemd/blob/main/man/udev.xml)

## macOS Apple Silicon: no port appears

Look for a detected `/dev/cu.usbmodem…` or `/dev/cu.usbserial…` port. In macOS
System Information, inspect **USB** to see whether the board is detected at all.
If absent, try a known data cable and a direct USB connection.

If USB detects the board but no serial port appears, identify its USB interface
from the board manufacturer's documentation. Native USB and USB-to-serial bridges
are different interfaces; do not select a driver solely from the display name.
[Espressif connection guidance](https://docs.espressif.com/projects/esp-idf/en/v5.2/esp32/get-started/establish-serial-connection.html)

For CP210x bridges, use [Silicon Labs VCP driver downloads](https://www.silabs.com/software-and-tools/usb-to-uart-bridge-vcp-drivers).
For CH340/CH341 bridges, consult [WCH's macOS driver page](https://www.wch-ic.com/downloads/CH341SER_MAC_ZIP.html).
Follow the vendor's compatibility and installation instructions for your macOS
version and Apple Silicon. Reconnect and refresh the app's ports afterward.
Linux group commands and udev rules do not apply to macOS.

## A port exists, but connection fails

Close other apps holding the port before retrying. Identification requires
compatible running firmware; a board in its ROM bootloader cannot answer
**Check display**. Reset normally to identify it.

For flashing failures, follow the board maker's BOOT/RESET and connector guidance
and the app's connection help. The supported displays do not necessarily share
the same connector or reset sequence. On Linux, another service such as
ModemManager can interfere; investigate a device-specific conflict rather than
disabling services globally.
[Espressif troubleshooting](https://docs.espressif.com/projects/esptool/en/latest/esp32/troubleshooting.html)
