# ESPImageServer

ESPImageServer is a free app that creates images and videos using AI models running locally on your own computer. Describe what you want to create, then save it to your Creation Library or send it to a supported ESP32 display over your local network.

**No API registration, API key, subscription, or per-generation fee is required.** Image and video generation runs on your NVIDIA GPU, not a paid cloud service. Internet access is needed to download the app, dependencies, and AI models; your prompts and generated images and videos stay on your computer.

## Download and install

**[Download installers from the latest release](https://github.com/thelastoutpostworkshop/ESPImageServer/releases/latest)**

Choose the installer for your computer from the release's **Assets** list:

| Platform | Installer | Generation setup |
| --- | --- | --- |
| Windows x64 | `ESPImageServer-Setup-<version>.exe` | Downloads dependencies during installation |
| Ubuntu 24.04 x64 | `ESPImageServer-<version>-linux-x64.deb` | Downloads dependencies automatically on first launch |

Both platforms require a supported NVIDIA GPU with CUDA for image and video generation. macOS installers are not included in the current release.

## Supported boards

| Board | Screen | Resolution | Touch supported by firmware |
| --- | --- | --- | --- |
| JC4827W543 | 4.3-inch IPS | 480 x 272 | Yes - capacitive GT911 variant |
| Waveshare ESP32-S3 LCD 3.16 | 3.16-inch LCD, ST7701 | 320 x 820 | No |
| Waveshare ESP32-C6 LCD 1.47 | 1.47-inch LCD | 172 x 320 | No |
| Cheap Yellow Display ESP32-2432S028R | 2.8-inch LCD, ILI9341 | 240 x 320 | No |
| Waveshare ESP32-S3 Touch AMOLED 1.43 | 1.43-inch round AMOLED | 466 x 466 | Yes - FT3168 |

Don't have a board? Open **Set up display > Buy a supported board** in the app for photos, purchase links, and guidance on choosing the correct variant.

Install compatible firmware through **Set up display** in the desktop app. Firmware packages are also available in the [ESPImageFirmware releases](https://github.com/thelastoutpostworkshop/ESPImageFirmware/releases/latest).

## What you need

- A Windows x64 or Ubuntu 24.04 x64 computer.
- For displaying your creations: a supported ESP32 board running compatible firmware, connected to the same local network. You can generate images and videos without a connected display.
- Enough free disk space for AI models. The first use of a model downloads its files.

Image and video generation require a working NVIDIA graphics card with CUDA.
Without CUDA, the app supports display management and saved creations; CPU
generation is disabled.

See [release installation instructions](https://github.com/thelastoutpostworkshop/ESPImageServer/releases/latest) for platform details. The app is free to use; you supply the computer, display hardware, storage, and electricity.

## Windows installation

1. Download `ESPImageServer-Setup-<version>.exe` from the [latest release](https://github.com/thelastoutpostworkshop/ESPImageServer/releases/latest).
2. Run the installer and follow the setup steps.
3. Choose NVIDIA CUDA acceleration for generation, or display management only for setup, saved creations, and SD-card tools.
4. Choose an initial image model. Its files download during setup or the first time you select it.
5. Open **ESPImageServer** from the Start Menu or desktop shortcut.

Setup uses CPython 3.12. If it is not already installed, the installer asks Windows Package Manager to install it; other Python versions already on the computer are left alone.

The desktop app starts the local server automatically. You can also open the app in a browser at `http://127.0.0.1:8000` while it is running.

## Linux installation

Download the `.deb` from the [latest release](https://github.com/thelastoutpostworkshop/ESPImageServer/releases/latest), then follow the [Ubuntu installation instructions in the release notes](https://github.com/thelastoutpostworkshop/ESPImageServer/releases/latest). Generation dependencies are downloaded automatically on first launch.

## Install firmware over USB

1. Connect your supported board to the computer using a USB data cable.
2. Open **Set up display** in the desktop app and follow the firmware installation instructions.
3. Configure Wi-Fi and wait for **Ready**.

## Connect your display

Start your ESP32 display on the same Wi-Fi network as the computer. Firmware 1.1.39 and later registers its compiled board target, firmware version, name, and screen size automatically. Update the app and firmware together: registration requires an explicit `board_target`. Automatic firmware update notifications use this identifier, never screen dimensions or a user-assigned name. Once connected, ESPImageServer shows the display name and resolution near the top of the app.

Generated images are automatically sized for the physical display. No manual image-size setup is needed.

If the display does not connect, confirm that:

- The computer and ESP32 are on the same local network.
- ESPImageServer is open and Windows Firewall allows it on private networks.
- The ESP32 firmware uses the correct server address, normally `http://espimageserver.local:8000`.

## Save to the display SD card

SD-card saves show download and verification progress. The app confirms a save after the display acknowledges the committed file. **Cancel save** remains pending until the display confirms cancellation. Thumbnails can finish later. Keep room for a temporary copy when replacing a file.

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
| DreamShaper 8 | Creative, illustrated, and fantasy artwork | NVIDIA graphics card with CUDA required |
| Segmind SSD-1B | More detailed, higher-quality images | NVIDIA graphics card with CUDA required |
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

CPU generation is not supported. Generation requires a working NVIDIA GPU with CUDA; computers without one can still manage displays, saved creations, and SD cards.

### A model appears to be stuck loading

The first download can take time, depending on the model size and internet connection. Keep the app open until it finishes. If a previously downloaded model is loading, it may take a moment to move the model into memory.

### The display orientation is wrong

Change **Image rotation** in the Generate page, then create a new image. Rotation applies to newly generated images.

### I cannot find my images

Open **Settings** and select **Open image library folder**. You can also use **Choose image library** to move future images to an empty folder.

## Privacy and network use

Image generation runs locally. Model downloads require internet access the first time a model is installed. After that, normal image generation and ESP32 image delivery use your computer and local network.

For developer setup, testing, and release instructions, see [CONTRIBUTING.md](CONTRIBUTING.md).
