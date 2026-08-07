@echo off
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo ESPImageServer is not installed correctly. Run the installer again.
    pause
    exit /b 1
)

echo Starting ESPImageServer...
echo Keep this window open while the ESP32 uses the server.
".venv\Scripts\python.exe" -m esp_image_server
if errorlevel 1 pause
