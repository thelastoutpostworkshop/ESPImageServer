# ESPImageServer

A small local Python server that turns a text prompt into a JPEG sized for an ESP32 display. The API returns raw JPEG bytes—no Base64 and no image storage.

The default model is [`stabilityai/sd-turbo`](https://huggingface.co/stabilityai/sd-turbo), used via Hugging Face Diffusers. It downloads on its first start and is much faster on an NVIDIA CUDA GPU. CPU works for validating the workflow but may take several minutes per image.

## Requirements

- Windows 11, macOS, or Linux
- Python 3.10+
- About 8 GB RAM; an NVIDIA GPU with sufficient VRAM is strongly recommended

Install a PyTorch build appropriate to the machine first. For NVIDIA CUDA, use the selector at [pytorch.org](https://pytorch.org/get-started/locally/). For a CPU-only proof of concept, this is sufficient:

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install --upgrade pip
pip install torch --index-url https://download.pytorch.org/whl/cpu
pip install -e ".[dev]"
```

## Run

```powershell
python -m esp_image_server
```

Startup logs show the listening address and selected device. The first run downloads the model; later starts use the local Hugging Face cache. Open `http://localhost:8000/docs` for the interactive API documentation.

## Generate an image

```powershell
$body = @{ prompt = 'A small robot exploring Mars, bright friendly illustration' } | ConvertTo-Json
Invoke-WebRequest -Uri http://localhost:8000/generate -Method POST -ContentType 'application/json' -Body $body -OutFile robot.jpg
```

The response is `Content-Type: image/jpeg` and can be written directly by an ESP32 HTTP client to a decoder or file. `GET /health` reports whether the model is ready and the selected device.

## Configuration

Set these environment variables before starting the server:

| Variable | Default | Meaning |
| --- | --- | --- |
| `ESP_IMAGE_MODEL` | `stabilityai/sd-turbo` | Any compatible local Diffusers text-to-image model |
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
