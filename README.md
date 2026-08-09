# ESPImageServer

A small local Python server that turns a text prompt into a JPEG sized for an ESP32 display. The API returns raw JPEG bytes—no Base64 and no image storage.

The default model is [`stabilityai/sd-turbo`](https://huggingface.co/stabilityai/sd-turbo), used via Hugging Face Diffusers. It downloads on its first start and is much faster on an NVIDIA CUDA GPU. CPU works for validating the workflow but may take several minutes per image.

## Requirements

- Windows 11, macOS, or Linux
- Python 3.10+
- About 8 GB RAM; an NVIDIA GPU with sufficient VRAM is strongly recommended

## Maker installer (Windows)

For a maker-facing installation, build and distribute `ESPImageServer-Setup.exe`. It opens a Windows wizard that lets the user select CPU or NVIDIA CUDA acceleration and choose a model. The installer downloads the selected model before it finishes, so the server is ready to use immediately. Models are stored in the user's local application data folder, separate from the program files, so installer upgrades preserve them.

To build it as a project developer, install [Inno Setup](https://jrsoftware.org/isinfo.php), then run:

```powershell
iscc installer\ESPImageServer.iss
```

The installer is created at `dist\ESPImageServer-Setup.exe`.

## Developer quick install (Windows)

Double-click `install.bat` in the project folder. If Python is absent, it installs Python 3.12 for the current Windows user with Windows Package Manager (`winget`), then creates an ignored `.venv` folder, installs the CPU PyTorch build, and installs ESPImageServer.

After it completes, start the server with:

```powershell
.venv\Scripts\python.exe -m esp_image_server
```

The CPU build makes the install work everywhere, but it is not practical for regular image generation. If the computer has an NVIDIA GPU, replace it with the CUDA build selected at [pytorch.org](https://pytorch.org/get-started/locally/) before starting the server.

Install a PyTorch build appropriate to the machine first. For NVIDIA CUDA, use the selector at [pytorch.org](https://pytorch.org/get-started/locally/). For a CPU-only proof of concept, this is sufficient:

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install --upgrade pip
pip install torch --index-url https://download.pytorch.org/whl/cpu
pip install -e ".[dev]"
```

## Web interface development

The browser app is a Vue 3 + Vite project in `frontend`. Install its developer dependencies and run it with:

```powershell
npm --prefix frontend install
npm --prefix frontend run dev
```

Keep FastAPI running on port 8000; Vite proxies its API requests there. Before building the Windows installer, create the production frontend bundle with `npm --prefix frontend run build`. The installer includes this bundle, so makers do not need Node.js or npm.

## Run

```powershell
python -m esp_image_server
```

Startup logs show the listening address and selected device. The first run downloads the model; later starts use the local Hugging Face cache. Open `http://localhost:8000/docs` for the interactive API documentation.

Open `http://127.0.0.1:8000/` for the browser test page. `0.0.0.0` in Uvicorn's startup message is a network bind address, not a browser URL. The server also advertises itself on the local network as `espimageserver.local`, so ESP32 devices can use that stable name instead of a changing LAN IP address.

On Windows, ESPImageServer advertises the active physical LAN address rather than WSL or Hyper-V virtual-network addresses.

The Start Menu and desktop launchers open this test page automatically after the server is ready. To do the same from another launcher, set `ESP_IMAGE_OPEN_BROWSER=1` before starting the server.

## Changing the image model

Open the **Models** item in the web app to select an available model. The app shows whether it is already on the computer. Choosing a new model downloads it if needed, loads it, and remembers the selection for the next server start. The current release includes SD-Turbo (fast, recommended), DreamShaper 8 (creative and artistic, NVIDIA recommended), Segmind SSD-1B (higher quality, NVIDIA recommended), and SDXL Base 1.0 (best detail, powerful NVIDIA GPU required).

## Generate an image

```powershell
$body = @{ prompt = 'A small robot exploring Mars, bright friendly illustration' } | ConvertTo-Json
Invoke-WebRequest -Uri http://localhost:8000/generate -Method POST -ContentType 'application/json' -Body $body -OutFile robot.jpg
```

The response is `Content-Type: image/jpeg` and can be written directly by an ESP32 HTTP client to a decoder or file. `GET /health` reports whether the model is ready and the selected device.

## Show images on an ESP32 display

Each generated image automatically becomes the current display image. An ESP32 on the same local network polls:

```text
http://espimageserver.local:8000/latest.jpg
```

The endpoint returns `204` until an image has been generated. It supplies an `ETag` with each JPEG; the ESP32 sends that value back as `If-None-Match` and receives `304` when nothing has changed. This keeps setup to Wi-Fi credentials only and avoids repeatedly downloading the same image.

The single ESP32 board announces its name and integrated screen dimensions to `POST /display`. The browser test page then uses that resolution automatically; for example, the JC4827W543 board reports `480x272`.

ESPImageServer generates on an aspect-matched canvas that is appropriate for the selected model, then precisely crops and resizes the JPEG for the reported screen. For a `480x272` display this is `512x288` with SD-Turbo and `1024x584` with SSD-1B. The browser does not offer manual image-size controls: the connected board is the source of truth.

## Configuration

Set these environment variables before starting the server:

| Variable | Default | Meaning |
| --- | --- | --- |
| `ESP_IMAGE_MODEL` | `stabilityai/sd-turbo` | Any compatible local Diffusers text-to-image model |
| `ESP_IMAGE_MODEL_CACHE` | Hugging Face default | Model-cache directory; the Windows installer sets this to the app's `models` folder |
| `ESP_IMAGE_HOST` | `0.0.0.0` | Bind address; use `0.0.0.0` for LAN ESP32 access |
| `ESP_IMAGE_PORT` | `8000` | HTTP port |
| `ESP_IMAGE_OUTPUT_WIDTH` | `466` | Returned JPEG width |
| `ESP_IMAGE_OUTPUT_HEIGHT` | `466` | Returned JPEG height |
| `ESP_IMAGE_JPEG_QUALITY` | `85` | JPEG quality, 1–100 |
| `ESP_IMAGE_GENERATION_WIDTH` | `512` | Model generation width, divisible by 8 |
| `ESP_IMAGE_GENERATION_HEIGHT` | `512` | Model generation height, divisible by 8 |

The server center-crops and resizes the generated image to the output dimensions. Model integration lives in `generator.py`, separate from the FastAPI routes, so a future model only needs to implement `load()` and `generate(prompt)`.

## Test

```powershell
pytest
```
