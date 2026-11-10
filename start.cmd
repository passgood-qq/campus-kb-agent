@echo off
chcp 65001 > nul
setlocal
cd /d "%~dp0"

rem 数据库的可执行文件目录，换机器时改这里或设环境变量 PG_BIN
if "%PG_BIN%"=="" set "PG_BIN=F:\dev\pg17\pgsql\bin"

echo ============================================
echo  campus-kb-agent  本地启动
echo  工作目录: %CD%
echo ============================================

echo.
echo [1/3] 检查 PostgreSQL ...
"%PG_BIN%\pg_ctl.exe" -D "%~dp0data" status > nul 2>&1
if errorlevel 1 (
    echo       未运行，正在启动...
    "%PG_BIN%\pg_ctl.exe" -D "%~dp0data" -l "%~dp0pg.log" start
    timeout /t 3 /nobreak > nul
) else (
    echo       已在运行
)

echo.
echo [2/3] 检查数据库里的资料量 ...
"%PG_BIN%\psql.exe" -w -U postgres -h 127.0.0.1 -d postgres -t -c "select 'documents=' || (select count(*) from documents) || '  chunks=' || (select count(*) from chunks);" 2>nul

echo.
echo [3/3] 启动 API 服务 ...
echo       页面: http://127.0.0.1:8000/
echo       文档: http://127.0.0.1:8000/docs
echo       按 Ctrl+C 停止服务
echo.
python -m uvicorn app.main:app --port 8000

endlocal
