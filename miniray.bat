@echo off
REM Miniray launcher for Windows. Double-click to open the shell,
REM or run from a terminal:  miniray.bat status
setlocal
cd /d "%~dp0"
where py >nul 2>nul
if %errorlevel%==0 (
    py -3 -m miniray %*
) else (
    python -m miniray %*
)
set MINIRAY_EXIT=%errorlevel%
REM Keep the window open when started by double-click with no arguments.
if "%~1"=="" pause
exit /b %MINIRAY_EXIT%
