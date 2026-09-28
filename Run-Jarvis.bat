@echo off
setlocal
set "APP_DIR=%~dp0"
set "PLAYWRIGHT_BROWSERS_PATH=%APP_DIR%playwright-browsers"
set "PYTHONUTF8=1"
if not exist "%APP_DIR%python\python.exe" (
    echo Portable Python was not found. Build the USB bundle first.
    pause
    exit /b 1
)
pushd "%APP_DIR%"
"%APP_DIR%python\python.exe" "%APP_DIR%main.py"
set "EXIT_CODE=%ERRORLEVEL%"
popd
if not "%EXIT_CODE%"=="0" pause
endlocal