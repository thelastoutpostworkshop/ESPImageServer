@echo off
setlocal EnableExtensions

rem ESPImageServer installer for Windows.
rem Creates a local virtual environment and installs the CPU PyTorch build.
rem For NVIDIA CUDA, follow the PyTorch instructions in README.md after setup.

cd /d "%~dp0"
set "VENV_DIR=%CD%\.venv"

echo.
echo === ESPImageServer setup ===
echo.

where py >nul 2>nul
if not errorlevel 1 (
    py -3.12 -c "import sys" >nul 2>nul
    if not errorlevel 1 (
        set "PYTHON=py -3.12"
    ) else (
        set "PYTHON=py"
    )
) else (
    where python >nul 2>nul
    if errorlevel 1 goto :missing_python
    set "PYTHON=python"
)

if not exist "%VENV_DIR%\Scripts\python.exe" (
    echo Creating a local Python environment...
    %PYTHON% -m venv "%VENV_DIR%" || goto :error
)

set "VENV_PYTHON=%VENV_DIR%\Scripts\python.exe"
echo Updating package tools...
"%VENV_PYTHON%" -m pip install --upgrade pip || goto :error

"%VENV_PYTHON%" -c "import torch" >nul 2>nul
if errorlevel 1 (
    echo Installing PyTorch CPU build...
    "%VENV_PYTHON%" -m pip install torch --index-url https://download.pytorch.org/whl/cpu || goto :error
) else (
    echo PyTorch is already installed.
)

echo Installing ESPImageServer dependencies...
"%VENV_PYTHON%" -m pip install -e . || goto :error

echo.
echo Setup complete.
echo.
echo Start the server with:
echo   .venv\Scripts\python.exe -m esp_image_server
echo.
echo The first server start downloads the image model. A CUDA-capable NVIDIA GPU
echo is strongly recommended; see README.md to replace the CPU PyTorch build.
goto :end

:missing_python
echo Python was not found.
echo Install Python 3.10 or newer from https://www.python.org/downloads/windows/
echo During installation, select "Add Python to PATH", then run this file again.
goto :end

:error
echo.
echo Setup failed. Review the error above, then run install.bat again.
exit /b 1

:end
endlocal
