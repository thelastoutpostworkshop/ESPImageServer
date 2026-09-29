# Contributing to ESPImageServer

Bug reports, documentation improvements, and focused pull requests are welcome.

## Report an issue

Describe what you expected and what happened. Include the app version, operating system, and relevant screenshots or logs. For generation issues, include your GPU and selected model; for display issues, include the board and firmware version. Remove passwords and other private information before sharing logs.

## Development setup

Use Python 3.12 and Node.js 22.12 or newer. From the repository root on Windows:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
npm --prefix frontend ci
npm --prefix desktop ci
npm --prefix frontend run build
.\.venv\Scripts\python.exe -m uvicorn esp_image_server.app:app --reload
```

On Linux or macOS, use `.venv/bin/python` instead. Open `http://127.0.0.1:8000`. Actual image and video generation requires a supported NVIDIA GPU with CUDA.

The backend is in `src/esp_image_server`, the web app in `frontend`, and the desktop shell in `desktop`. ESP32 firmware is maintained in a separate repository.

## Submit a change

Keep changes focused, preserve user data, and use plain language in the app. Run the checks relevant to your change:

```powershell
.\.venv\Scripts\python.exe -m pytest
npm --prefix frontend test
npm --prefix frontend run build
npm --prefix desktop test
```

Check visible changes in the running app. In your pull request, explain what changed and which checks you ran. Mention any effect on firmware compatibility. Do not commit credentials, model downloads, virtual environments, logs, or generated installers.
