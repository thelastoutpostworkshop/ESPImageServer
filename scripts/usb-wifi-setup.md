# Guided USB setup (firmware 1.1.3; Wi-Fi reset in 1.1.4)

Implementation is ready for manual firmware compilation and hardware testing.
The installed desktop executable must be updated or replaced with the development
checkout; rebuilding the frontend alone does not update Electron's preload API.
Export a fresh package from the compiled version; never relabel older binaries.

## Protocol

The identification protocol remains version 1 at 115200 baud. Firmware advertises
`wifi_scan`, `wifi_connect`, `wifi_cancel`, and `wifi_status` in `hello` capabilities.
Every Wi-Fi request includes the board's `hardware_id`; a mismatch is rejected
before processing credentials. Responses never contain passwords. Requests retain
the 1024-byte limit; desktop responses are bounded to 16384 characters.

`wifi_scan` starts an asynchronous scan. `wifi_connect` accepts `ssid`, `password`,
and `auth` (`personal` or `open`) and starts a fresh association. SSIDs are 1–32
UTF-8 bytes without NUL. WPA2 passphrases are 8–63 printable ASCII characters or
64 hexadecimal digits; open networks require an empty password. Hidden SSIDs
are entered manually. Scan results include at most 20 SSID/auth combinations,
their RSSI, and `open`, `personal`, or `unsupported` authentication classification.

`wifi_status` returns `wifi_state`, `wifi_error`, `wifi_reason`, `wifi_configured`,
`wifi_connected`, `ip`, and `networks`. The host polls every 500 ms on one open
serial session. States are `idle`, `scanning`, `scan_complete`, `connecting`,
`obtaining_ip`, `connected`, `cancelled`, and `failed`. Scan and connect deadlines
are 20 and 30 seconds. `wifi_cancel` stops pending work and restores previous
credentials; it does not undo a completed save. Eight seconds without a Wi-Fi
request cancels active work. Read-only `hello` does not extend that lease.

Firmware 1.1.4 also advertises `wifi_forget`. It requires the matching hardware
ID and boolean `confirm: true`; the desktop sends this only after confirmation.
It rejects active scans/connections. Success returns `wifi_state: forgotten`,
both Wi-Fi flags false, and an empty IP. Storage failure returns `forget_failed`.
An empty versioned NVS record prevents old legacy credentials from being loaded
again after a power cut; legacy Wi-Fi keys are then removed. Other settings and
SD files are untouched. Firmware 1.1.3 supports Change Wi-Fi but not Forget Wi-Fi.

The firmware USB task alone starts scans/connections. Other tasks read atomic
configured/ready/busy snapshots. Saved-network retries wait five seconds after a
failed attempt. Driver persistence is disabled before credentials are submitted.
New credentials are saved as one versioned NVS blob (`espimage/wifi_v1`) after
obtaining an IP. Legacy `ssid`/`password` are read only when the blob is absent;
unchanged credentials avoid a flash write. NVS open/write/commit errors are checked.
Display/SD settings are separate. No hotspot or compiled personal credentials are used.

The desktop shares the flashing lock, rechecks hardware identity before sending
credentials, sanitizes protocol/driver errors, and closes the port on all terminal
paths. Cancelling or closing the app requests cancellation. USB loss cannot prove
whether saving already completed: identify again after reconnecting.

## Manual acceptance

1. Manually compile JC4827W543 firmware 1.1.4 and export a new manifest package.
   Build the frontend, close the older desktop instance, and run
   `npm --prefix desktop start` from the app repo. Flash the new package and
   verify the board/version/hardware ID. No installer rebuild is required.
2. With no saved Wi-Fi, verify USB setup guidance on the board. Scan, select
   a supported network, enter its password, and connect. Observe connecting,
   obtaining IP (which may be brief), and connected/saved. Confirm password
   removal from the UI and absence from logs, responses, and desktop storage.
3. Power-cycle the board. Confirm it reconnects without password entry. Check
   LAN registration and image delivery separately from USB Wi-Fi success.
4. Replace a working network with a wrong password, including for the SAME
   SSID. Verify it fails and the previous credentials still work after reboot.
   Repeat with a missing SSID, hidden network, and open network.
5. Cancel a scan/connection, unplug USB during connection, and close the app
   during setup. Verify eventual recovery and released COM port. If power is
   also removed, reconnect and check which credential record survived.
6. Interrupt power during credential replacement. Confirm one complete old or
   new record survives, never a mixed SSID/password pair. Use a controlled test
   build to inject NVS open/write/commit failure; confirm a useful error and
   preservation of prior configuration. Do not erase NVS to simulate this.
7. Repeat identification/setup while offline slideshow/video and server retries
   run. Confirm USB remains responsive and no competing scans occur.
8. Repeat with the server unavailable: valid Wi-Fi must still save. Test busy
   COM port, old firmware, and swapping boards on the same COM port; no
   credentials should be sent to a mismatched device.
9. In **Set up display**, identify an already compatible board: flashing should
   be optional. Ready requires fresh `/displays` contact with matching hardware
   ID, version, and dimensions. Another online board or stale registration must
   not satisfy this check. Unplug/replug and change ports; identify again before
   setup. **Use this display** must open the matched board. Verify image delivery.
10. Confirm Forget Wi-Fi on a designated test board. It must disconnect and show
    USB setup guidance. Power-cycle: credentials must stay forgotten, including
    when legacy keys existed. Verify SD files and other settings survived, then
    provision again. Cancelling the confirmation must leave the board unchanged.
    Test storage failures and interrupted reset separately on a controlled build.

Hardware evidence: on 2026-09-12 the user confirmed JC4827W543 firmware 1.1.3
connected through USB setup and reconnected after a power cycle. Step 4 reset,
server handoff, and failure scenarios still require hardware acceptance.

Automated tests use fake serial devices; they do not validate firmware execution,
radio behavior, NVS fault recovery, or physical power interruption.

API references: [Arduino-ESP32 Wi-Fi](https://docs.espressif.com/projects/arduino-esp32/en/latest/api/wifi.html)
and [Espressif NVS](https://docs.espressif.com/projects/esp-idf/en/latest/esp32/api-reference/storage/nvs_flash.html).
