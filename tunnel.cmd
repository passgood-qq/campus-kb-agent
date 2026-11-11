@echo off
chcp 65001 > nul
cd /d "%~dp0"

echo ============================================
echo  临时公网链接（Cloudflare Quick Tunnel）
echo  免账号、免费，但：电脑关机即断，链接每次变
echo ============================================
echo.

if not exist "cloudflared.exe" (
    echo 首次运行，正在下载 cloudflared ^(约 40MB^) ...
    curl -L -o cloudflared.exe https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-windows-amd64.exe
    if errorlevel 1 (
        echo 下载失败，请检查网络后重试。
        pause
        exit /b 1
    )
)

echo.
echo 请先确保服务已在 8000 端口运行（另开窗口跑 start.cmd）
echo 按任意键开始建立隧道 ...
pause > nul

cloudflared.exe tunnel --url http://127.0.0.1:8000
