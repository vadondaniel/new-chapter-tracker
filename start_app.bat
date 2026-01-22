@echo off
setlocal
cd /d "%~dp0"

REM Check if virtual environment exists
if exist .venv\Scripts\pythonw.exe (
    echo Starting Chapter Tracker using virtual environment...
    start "" ".venv\Scripts\pythonw.exe" new_chapters.py
) else (
    echo Virtual environment not found, trying system pythonw...
    where pythonw >nul 2>nul
    if %ERRORLEVEL% equ 0 (
        start "" pythonw new_chapters.py
    ) else (
        echo Error: pythonw.exe not found. Please ensure Python is installed and in your PATH.
        pause
        exit /b 1
    )
)

echo.
echo Chapter Tracker is now running in the background.
echo Look for the icon in your system tray to open or exit the app.
echo.
timeout /t 5
