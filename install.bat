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

call :find_python
if not defined PYTHON (
    echo Python was not found. Installing Python 3.12 for this user...
    where winget >nul 2>nul
    if errorlevel 1 goto :missing_winget
    winget install --id Python.Python.3.12 --exact --scope user --accept-package-agreements --accept-source-agreements || goto :error
    call :find_python
    if not defined PYTHON goto :python_not_available
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

:missing_winget
echo Python was not found and Windows Package Manager ^(winget^) is unavailable.
echo Install Python 3.12 from https://www.python.org/downloads/windows/ and run this file again.
goto :end

:python_not_available
echo Python was installed, but the Python launcher is not available yet.
echo Close this window, open install.bat again, and setup will continue.
goto :end

:error
echo.
echo Setup failed. Review the error above, then run install.bat again.
exit /b 1

:end
endlocal
exit /b 0

:find_python
set "PYTHON="
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
    if not errorlevel 1 set "PYTHON=python"
)
exit /b 0
