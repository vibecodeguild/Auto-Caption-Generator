@echo off
setlocal
cd /d "%~dp0"

set "APP_PYTHON=.venv\Scripts\pythonw.exe"
if exist "%APP_PYTHON%" goto :paths

where pythonw.exe >nul 2>nul
if not errorlevel 1 (
    set "APP_PYTHON=pythonw.exe"
    goto :paths
)

echo Python runtime not found.
echo Create a virtual environment and install dependencies first:
echo.
echo   py -3 -m venv .venv
echo   .venv\Scripts\python.exe -m pip install -r requirements.txt
echo.
pause
exit /b 1

:paths
if exist ".venv\Lib\site-packages\nvidia\cublas\bin" set "PATH=%CD%\.venv\Lib\site-packages\nvidia\cublas\bin;%PATH%"
if exist ".venv\Lib\site-packages\nvidia\cuda_runtime\bin" set "PATH=%CD%\.venv\Lib\site-packages\nvidia\cuda_runtime\bin;%PATH%"
if exist ".venv\Lib\site-packages\nvidia\cuda_nvrtc\bin" set "PATH=%CD%\.venv\Lib\site-packages\nvidia\cuda_nvrtc\bin;%PATH%"
if exist ".venv\Lib\site-packages\nvidia\cudnn\bin" set "PATH=%CD%\.venv\Lib\site-packages\nvidia\cudnn\bin;%PATH%"

start "" "%APP_PYTHON%" "%CD%\run_app.py"
exit /b 0
