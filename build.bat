@echo off
set _CL_=/utf-8
chcp 65001 >nul

:: 强行结束可能仍在运行的旧程序，防止文件锁死导致 Access is denied
taskkill /f /im WowsAnalyzer.exe 2>nul

set PYTHON=.venv\Scripts\python.exe
set OUTDIR=release

:: 如果文件被杀毒软件等临时锁死，尝试强力删除旧 exe
if exist "%OUTDIR%\WowsAnalyzer.exe" del /f /q "%OUTDIR%\WowsAnalyzer.exe" 2>nul

:: 编译 onefile 可执行文件
%PYTHON% -m nuitka ^
    --standalone ^
    --onefile ^
    --output-dir="%OUTDIR%" ^
    --windows-console-mode=disable ^
    --enable-plugin=pyside6 ^
    --include-data-file="tools/*.exe=tools/" ^
    --include-data-dir="resources=resources" ^
    --include-module=services.GameParams ^
    --output-filename=WowsAnalyzer.exe ^
    main.py

if %ERRORLEVEL% NEQ 0 (
    echo.
    echo [! ERROR] Nuitka build failed.
    pause
    exit /b %ERRORLEVEL%
)

:: 将 config.json 复制到 exe 同级目录下
if exist "config.json" (
    copy /y "config.json" "%OUTDIR%\config.json" >nul
    echo [OK] config.json 已成功部署到外部 release 目录。
) else (
    echo [WARN] 未在根目录找到 config.json 模板，程序首次运行时会自动创建默认配置。
)

:: 精准清理 Nuitka 产生的所有中间缓存文件夹
rd /s /q "%OUTDIR%\main.build" 2>nul
rd /s /q "%OUTDIR%\main.dist" 2>nul
rd /s /q "%OUTDIR%\main.onefile-build" 2>nul

echo Build Successful!
timeout /t 3
exit