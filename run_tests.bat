@echo off
REM Runs Miniray's test suite on Windows.
setlocal
cd /d "%~dp0"
where py >nul 2>nul
if %errorlevel%==0 (
    py -3 -m unittest discover -s tests -v
) else (
    python -m unittest discover -s tests -v
)
pause
