@echo off
setlocal
cd /d "%~dp0"

if not exist "app\temp" mkdir "app\temp"
del "app\temp\startup.log" >nul 2>nul

set "APP_PYTHON=.venv\Scripts\pythonw.exe"
if exist "%APP_PYTHON%" goto :paths

echo Project virtual environment not found.
echo Create the local environment and install dependencies first:
echo.
echo   py -3 -m venv .venv
echo   .venv\Scripts\python.exe -m pip install -r requirements.txt
echo.
> "app\temp\startup.log" echo Project virtual environment not found. Create .venv and install requirements.txt.
pause
exit /b 1

:paths
if exist ".venv\Lib\site-packages\nvidia\cublas\bin" set "PATH=%CD%\.venv\Lib\site-packages\nvidia\cublas\bin;%PATH%"
if exist ".venv\Lib\site-packages\nvidia\cuda_runtime\bin" set "PATH=%CD%\.venv\Lib\site-packages\nvidia\cuda_runtime\bin;%PATH%"
if exist ".venv\Lib\site-packages\nvidia\cuda_nvrtc\bin" set "PATH=%CD%\.venv\Lib\site-packages\nvidia\cuda_nvrtc\bin;%PATH%"
if exist ".venv\Lib\site-packages\nvidia\cudnn\bin" set "PATH=%CD%\.venv\Lib\site-packages\nvidia\cudnn\bin;%PATH%"

start "" "%APP_PYTHON%" "%CD%\run_app.py"
exit /b 0
