@echo off
setlocal
echo Stopping Chapter Tracker...

REM Try to kill by process name (pythonw.exe running new_chapters.py)
REM We use taskkill with a filter to be safer, though multiple pythonw processes might exist.
REM The most reliable way is usually through the tray icon, but this is a CLI alternative.

taskkill /F /FI "IMAGENAME eq pythonw.exe" /FI "WINDOWTITLE eq Chapter Tracker" >nul 2>nul

REM If that didn't work (since pythonw often has no window title), 
REM we can try to find the process that has the script name in its command line.
REM However, taskkill doesn't support command line filtering easily.
REM We'll use PowerShell for a more precise kill if needed.

powershell -Command "Get-Process pythonw -ErrorAction SilentlyContinue | Where-Object { $_.CommandLine -like '*new_chapters.py*' } | Stop-Process -Force"

echo.
echo If the app was running, it has been stopped.
echo Note: You can also exit the app by right-clicking the tray icon.
echo.
timeout /t 3
