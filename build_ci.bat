@echo off
set _CL_=/utf-8
chcp 65001 >nul

:: ═══════════════════════════════════════════════════════════════
:: GitHub Actions 专用「纯净构建脚本」
::   只做一件事：产出 release\KorabliParagrams.exe 供上传到 Release。
::   不含本地专属步骤（D 盘临时目录重定向、taskkill 旧进程、
::   config.json 复制、pause、timeout），与 build.bat（本地）解耦。
::   调用方：.github/workflows/release.yml 的 Build exe 步骤。
:: ═══════════════════════════════════════════════════════════════

set PYTHON=.venv\Scripts\python.exe
set OUTDIR=release

:: Python 强制 UTF-8 模式：CI 管道默认 cp1252 会 UnicodeEncodeError
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8

:: ── 步骤 1: 生成并编译 Qt 资源文件（QRC → _resources.py） ──
echo [QRC] 生成 resources.qrc ...
%PYTHON% scripts/gen_qrc.py
if %ERRORLEVEL% NEQ 0 exit /b %ERRORLEVEL%
echo [QRC] 编译 _resources.py ...
set RCC_TOOL=.venv\Lib\site-packages\PySide6\rcc.exe
if exist "%RCC_TOOL%" (
    "%RCC_TOOL%" -g python resources.qrc -o app/_resources.py
) else (
    %PYTHON% -m PySide6.rcc resources.qrc -o app/_resources.py 2>nul
    if %ERRORLEVEL% NEQ 0 (
        pyside6-rcc resources.qrc -o app/_resources.py
    )
)
if %ERRORLEVEL% NEQ 0 exit /b %ERRORLEVEL%
echo [QRC] 资源编译完成。

:: ── 步骤 1.5: 从 Git Tag 生成版本文件（含 pre-release 版本号） ──
echo [VERSION] 从 Git Tag 生成 __about__.py ...
%PYTHON% scripts/gen_version.py
if %ERRORLEVEL% NEQ 0 exit /b %ERRORLEVEL%

:: ── 步骤 2: 编译 onefile 可执行文件 ──
:: CI 用 MinGW gcc（--mingw64）+ 关闭 LTO（--lto=no）尝试规避 runner 自带
:: MSVC 的全量慢编译；--assume-yes-for-downloads 让 Nuitka 自动下载 gcc 等依赖。
%PYTHON% -m nuitka ^
    --standalone ^
    --onefile ^
    --mingw64 ^
    --lto=no ^
    --output-dir="%OUTDIR%" ^
    --windows-console-mode=attach ^
    --enable-plugin=pyside6 ^
    --assume-yes-for-downloads ^
    --include-module=app._resources ^
    --include-module=services.GameParams ^
    --include-package=meshoptimizer ^
    --output-filename=KorabliParagrams.exe ^
    main.py

if %ERRORLEVEL% NEQ 0 (
    echo [! ERROR] Nuitka build failed.
    exit /b %ERRORLEVEL%
)

:: 精准清理 Nuitka 产生的所有中间缓存文件夹（产物 exe 保留在 %OUTDIR%）
rd /s /q "%OUTDIR%\main.build" 2>nul
rd /s /q "%OUTDIR%\main.dist" 2>nul
rd /s /q "%OUTDIR%\main.onefile-build" 2>nul

echo Build Successful!
exit /b 0
