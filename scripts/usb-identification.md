# USB identification protocol v1

Firmware 1.1.2 accepts read-only newline-delimited JSON at 115200 baud on the
board's configured Serial stream (native USB CDC or UART bridge).

Request (one line):

```json
{"protocol":1,"id":"example-1","command":"hello"}
```

`status` returns the same current identity/status fields. Each response starts
with `@ESPIMAGE ` followed by JSON and a newline. JSON contains `protocol: 1`,
the matching `id`, `ok`, and either `result` or `error`. Result fields:

- `hardware_id`: the same 12-digit lowercase hex ID used for LAN registration.
- `board_target`, `board_name`, `firmware_version`, `protocol_version`.
- `width`, `height`, `capabilities` (`hello` and `status`).
- `wifi_configured`, `wifi_connected` (booleans). No credentials are returned.

Requests are limited to 1024 bytes excluding CR/LF. IDs contain 1-64 ASCII
letters, digits, or hyphens. Malformed/oversized requests are discarded through
newline; partial requests expire after two seconds idle. Requests with a valid
ID but unsupported protocol/command receive an error. A separate firmware task
services serial input while display/network code runs. The host skips ordinary
boot logs, bounds response lines, and matches IDs before accepting replies.

The desktop holds one operation lock for identification and flashing. Serial
ports close on success, timeout, and errors before the next operation. No reset
sequence is deliberately sent during identification, though some boards/drivers
can reset on port open. Repeated hello requests tolerate startup delays.

Manual acceptance for the new firmware:

1. Compile the selected board manually as version 1.1.2. Export a fresh package
   into a new version folder and regenerate its manifest with version 1.1.2.
2. Start the updated desktop app (`npm --prefix desktop start`). Flash the new
   package and confirm the automatic USB identity matches the board and version.
3. Check **Identify firmware** before/after unplugging USB, including a changed
   COM number. With two boards, verify each hardware ID and ambiguous-port handling.
4. Check an older build's timeout, busy serial port, malformed and oversized
   requests, then a valid request. Confirm recovery and normal display behavior.
5. Repeat identification during Wi-Fi connection retries and offline playback.

The automated desktop suite uses fake serial devices; it does not compile or
execute the Arduino firmware. Firmware 1.1.3 adds
[USB Wi-Fi setup](usb-wifi-setup.md); 1.1.2 identification remains compatible.

Desktop packaging uses the pinned serialport 13.0.0 package's Windows x64
Node-API prebuild. `npmRebuild` is disabled and prebuild files are unpacked from
ASAR so packaging does not require Visual Studio. If native dependencies or
target architectures change, recheck this setting and smoke-test loading the
serial binding in the actual Electron runtime, not only system Node.js.
