@echo off
setlocal
cd /d "%~dp0"

echo ==========================================
echo   Cloudflare Quick Tunnel
echo   Free, no account needed.
echo   PC must stay on. URL changes each run.
echo ==========================================
echo.

if not exist "cloudflared.exe" (
    echo Downloading cloudflared ^(about 40MB^) ...
    curl -L -o cloudflared.exe https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-windows-amd64.exe
    if errorlevel 1 (
        echo.
        echo Download failed. Check your network and retry.
        pause
        exit /b 1
    )
    echo Download complete.
)

echo.
echo Make sure the app is already running on port 8000
echo   open another window and run start.cmd first
echo.
echo Press any key to start the tunnel ...
pause > nul

cloudflared.exe tunnel --url http://127.0.0.1:8000

endlocal
