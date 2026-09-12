# ESPImageServer

ESPImageServer creates AI images and video on your own computer and sends them to an ESP32 display on your local network. Describe the image or the video you want, choose a model, and generate an image or video sized exactly for your connected display.

Your prompts, generated images, and model files stay on your computer. The ESP32 only downloads the finished JPEG or MJPEG from your local network.

## What you need

- A Windows computer.
- An ESP32 display running compatible ESPImageServer firmware and connected to the same Wi-Fi network.
- Enough free disk space for AI models. The first use of a model downloads its files.

ESPImageServer works best with an NVIDIA graphics card. It can run on the computer processor instead, but image and video generation may take very long.

## Install

1. Download the latest `ESPImageServer-Setup-<version>.exe` installer.
2. Run the installer and follow the setup steps.
3. Choose CPU mode or NVIDIA graphics card acceleration when prompted.
4. Choose an initial image model. Its files download during setup or the first time you select it.
5. Open **ESPImageServer** from the Start Menu or desktop shortcut.

Setup uses CPython 3.12. If it is not already installed, the installer asks Windows Package Manager to install it; other Python versions already on the computer are left alone.

The desktop app starts the local server automatically. You can also open the app in a browser at `http://127.0.0.1:8000` while it is running.

## Install firmware over USB (local packages)

In the desktop app, open **Set up display**. Connect a USB data cable, select
the COM port, and choose **Check display**. Setup shows one stage at a time:
Connect, Firmware, Wi-Fi, and Ready. The Creation Library panel closes to leave
room for setup. Compatible firmware can continue without installation.

Choose a **firmware library** once (for example your `ESPImage Firmwares` folder).
The desktop remembers its location and validates packages in the root, board,
and version folders. It compares stable versions only for the identified board,
shows **Update available**, and offers **Review update** or **Continue with
current version**. **Up to date in your library** refers only to that local source;
there is no online update catalog. Use **Check for updates** after adding packages.
Missing/unreadable libraries and invalid packages do not imply up-to-date firmware.

To install manually, choose **Install a different package** (or **Choose firmware
package** for incompatible firmware), then choose the version folder holding
`manifest.json` and its four binaries. Review the package and replacement notice,
check the confirmation box, and select **Install firmware**. The app checks the
package, connected chip, and flash capacity before writing. It reports the write
verification separately from application startup: check the board's screen for
the expected firmware version afterward. Firmware 1.1.3 adds USB Wi-Fi setup.
The connection-help panel covers manual bootloader entry and retries.

This is a first-install flow, not a guaranteed settings-preserving update. It
does not erase the entire flash or change SD-card files, but a different old
partition layout can make existing settings unavailable. Keep USB connected and
wait for the result before closing the app. Close other serial monitors first.

For a development checkout, start the updated desktop shell with:

```powershell
npm --prefix frontend run build
npm --prefix desktop start
```

Close an older desktop instance first. The first start/build downloads the pinned
official esptool 5.1.0 Windows archive and verifies its checksum. Subsequent starts
use the verified local copy. Desktop packaging includes esptool and its license,
but does not bundle firmware packages or require a separate Python/Arduino install
for flashing. The existing image-generation server still uses its Python setup.
No installer rebuild is needed to test the development checkout.

Firmware 1.1.2 adds read-only USB identification. Select a COM port and choose
**Check display** to read the hardware ID, model, version, dimensions, and
Wi-Fi status without installing anything. After flashing, the app also attempts
this check automatically. It follows a changed COM number only when the USB
serial identity uniquely matches the selected device; otherwise refresh ports
and identify it manually. Older firmware can still be flashed but cannot answer
the identification request. Successful writes remain reported even when startup
identification times out.

With firmware 1.1.3 and the updated desktop shell, identify the board, then use
**Wi-Fi setup over USB**. Scan networks or enter a hidden SSID, select WPA2
Personal or Open, and choose **Connect and save**. This flow supports 2.4 GHz
WPA2 Personal (including mixed WPA2/WPA3) and open networks. It does not support
enterprise, WEP, WPA-only, or WPA3-only networks. Scanning briefly disconnects
Wi-Fi. Passwords are sent over USB and are not saved by the desktop app.

The board tests a new connection before saving credentials, including when
replacing credentials for its current network. Failed/cancelled attempts restore
previous settings. A successful save survives reboot even if ESPImageServer is
unavailable. If USB is interrupted, reconnect and identify the board: a completed
connection may already have saved; otherwise the abandoned attempt is cancelled
after eight seconds. See [USB Wi-Fi tests](scripts/usb-wifi-setup.md) before release.

The final server check shows **Ready** only after fresh LAN contact matches the
USB board's hardware ID, firmware version, and dimensions. Saved Wi-Fi is checked
automatically after reboot, with up to three USB checks at ten-second intervals;
manual retry is available afterward. If discovery fails,
keep the app running and check the local network/server address; saved Wi-Fi
does not need to be entered again. **Open display** opens its display page.
**Send a test image** lets you choose an existing saved image and queue it for
this exact board. Check the physical screen to confirm delivery; queued is not
proof that it was displayed. This replaces the currently displayed content.
Changing ports or unplugging requires identification again.

**Manage Wi-Fi** on the Ready screen contains Change Wi-Fi and Forget Wi-Fi.
With firmware 1.1.4 or later,
**Forget Wi-Fi…** asks for confirmation before disconnecting and removing only
that board's Wi-Fi credentials. SD files and other display settings are preserved.

See [the contributor guide](CONTRIBUTING.md#create-a-local-firmware-package-and-manifest)
for the manifest script, required files, and packaging commands, or
[firmware package details](scripts/firmware-packages.md) for validation rules.
Run `npm --prefix desktop test` for hardware-free installer tests.

## Connect your display

Start your ESP32 display on the same Wi-Fi network as the computer. The board registers its name and screen size automatically. Once connected, ESPImageServer shows the display name and resolution near the top of the app.

Generated images are automatically sized for the physical display. No manual image-size setup is needed.

If the display does not connect, confirm that:

- The computer and ESP32 are on the same local network.
- ESPImageServer is open and Windows Firewall allows it on private networks.
- The ESP32 firmware uses the correct server address, normally `http://espimageserver.local:8000`.

## Create an image

1. Open **Generate image**.
2. Choose an image model and, if needed, an image rotation.
3. Describe the scene in the prompt box.
4. Optionally adjust **Generation steps** or use a seed to repeat a variation.
5. Select **Generate**.

The new image is sent to the connected ESP32 when generation finishes. It is also saved to the Creation Library by default.

### Prompts, seeds, and steps

- **Prompt**: what you want to see. Be specific about subject, style, lighting, and mood.
- **Seed**: a number that helps reproduce a result. Use the same prompt, model, settings, and seed for the closest repeat; create a random seed for a new variation.
- **Steps**: how long the model spends refining the image. More steps can add detail but take longer.
- **Rotation**: changes the image orientation for the physical display. It is applied by ESPImageServer, so the board receives an image in its native dimensions.

## Choose a model

Open **Models** to choose the look and quality level you want.

| Model | Best for | Computer guidance |
| --- | --- | --- |
| SD-Turbo | Fast experiments and everyday display images | Works on CPU or NVIDIA graphics cards |
| DreamShaper 8 | Creative, illustrated, and fantasy artwork | NVIDIA graphics card recommended |
| Segmind SSD-1B | More detailed, higher-quality images | NVIDIA graphics card recommended |
| SDXL Base 1.0 | The richest detail and prompt understanding | Powerful NVIDIA graphics card required |

When you choose a model for the first time, ESPImageServer says it is **Downloading and loading** it. Later, it says **Loading** because the model is already on your computer and only needs to be prepared for image generation.

Your selected model is remembered after you close the app. Installer upgrades keep downloaded models too.

## Use the Creation Library

The Creation Library keeps your generated images and their settings together.

- Open **Creation Library** from the app bar.
- Select an image to review its prompt, model, steps, seed, and rotation.
- Right-click a thumbnail to reuse just its prompt, seed, steps, model, or rotation in the generator.
- Choose **Use all** to restore all of that image's generation settings.

In **Settings**, you can choose where the image library is stored, open that folder, and turn automatic saving on or off. Your library location and settings survive app upgrades. A user-selected library folder is preserved if you uninstall ESPImageServer.

## Troubleshooting

### Generation is slow

CPU generation is expected to be slow, especially with larger models. Try SD-Turbo, use fewer steps, or use a computer with a compatible NVIDIA graphics card.

### A model appears to be stuck loading

The first download can take time, depending on the model size and internet connection. Keep the app open until it finishes. If a previously downloaded model is loading, it may take a moment to move the model into memory.

### The display orientation is wrong

Change **Image rotation** in the Generate page, then create a new image. Rotation applies to newly generated images.

### I cannot find my images

Open **Settings** and select **Open image library folder**. You can also use **Choose image library** to move future images to an empty folder.

## Privacy and network use

Image generation runs locally. Model downloads require internet access the first time a model is installed. After that, normal image generation and ESP32 image delivery use your computer and local network.

For developer setup, testing, and release instructions, see [CONTRIBUTING.md](CONTRIBUTING.md).
