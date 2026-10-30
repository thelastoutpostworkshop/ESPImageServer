@echo off
setlocal
cd /d "%~dp0"

if exist "server_settings.bat" call "server_settings.bat"

if not exist "runtime\python.exe" (
    echo ESPImageServer is not installed correctly. Run the installer again.
    pause
    exit /b 1
)

echo Starting ESPImageServer...
echo Keep this window open while the ESP32 uses the server.
set "ESP_IMAGE_OPEN_BROWSER=1"
set "PYTHONHOME="
set "PYTHONPATH="
"runtime\python.exe" -I -m esp_image_server
if errorlevel 1 pause
