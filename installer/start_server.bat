@echo off
setlocal
cd /d "%~dp0"

if exist "server_settings.bat" call "server_settings.bat"

if not exist ".venv\Scripts\python.exe" (
    echo ESPImageServer is not installed correctly. Run the installer again.
    pause
    exit /b 1
)

echo Starting ESPImageServer...
echo Keep this window open while the ESP32 uses the server.
start "ESPImageServer browser test" /b powershell.exe -NoProfile -WindowStyle Hidden -Command "$deadline = (Get-Date).AddMinutes(3); while ((Get-Date) -lt $deadline) { try { Invoke-WebRequest -UseBasicParsing http://127.0.0.1:8000/health ^| Out-Null; Start-Process http://127.0.0.1:8000/; exit } catch { Start-Sleep -Seconds 2 } }"
".venv\Scripts\python.exe" -m esp_image_server
if errorlevel 1 pause
