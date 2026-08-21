@echo off
set _CL_=/utf-8
chcp 65001 >nul

:: CI 模式：set CI_MODE=1 时跳过本地 D 盘重定向与 pause（GitHub Actions 用）
if not defined CI_MODE set CI_MODE=0

:: ── 0. 重定向 Nuitka 编译缓存 / 临时构建目录到 D 盘（避免占用 C 盘；仅本地构建） ──
if "%CI_MODE%"=="0" (
    set NUITKA_CACHE_DIR=D:\nuitka_cache
    set TMPDIR=D:\nuitka_tmp
    set TEMP=D:\nuitka_tmp
    set TMP=D:\nuitka_tmp
    if not exist "D:\nuitka_cache" mkdir "D:\nuitka_cache"
    if not exist "D:\nuitka_tmp" mkdir "D:\nuitka_tmp"
)

:: 强行结束可能仍在运行的旧程序，防止文件锁死导致 Access is denied
if "%CI_MODE%"=="0" taskkill /f /im KorabliParagrams.exe 2>nul

set PYTHON=.venv\Scripts\python.exe
set OUTDIR=release

:: Python 强制 UTF-8 模式：gen_qrc.py 等含中文输出，CI 管道默认 cp1252 会
:: UnicodeEncodeError（chcp 65001 只改控制台代码页，不影响 runner 捕获的管道编码）
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8

:: 如果文件被杀毒软件等临时锁死，尝试强力删除旧 exe
if exist "%OUTDIR%\KorabliParagrams.exe" del /f /q "%OUTDIR%\KorabliParagrams.exe" 2>nul

:: ── 步骤 1: 生成并编译 Qt 资源文件（QRC → _resources.py） ──
echo [QRC] 生成 resources.qrc ...
%PYTHON% scripts/gen_qrc.py
if %ERRORLEVEL% NEQ 0 (
    echo [! ERROR] QRC 生成失败
    if "%CI_MODE%"=="0" pause
    exit /b %ERRORLEVEL%
)
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
if %ERRORLEVEL% NEQ 0 (
    echo [! ERROR] QRC 编译失败
    if "%CI_MODE%"=="0" pause
    exit /b %ERRORLEVEL%
)
echo [QRC] 资源编译完成。

:: ── 步骤 1.5: 从 Git Tag 生成版本文件（Nuitka 编译前） ──
echo [VERSION] 从 Git Tag 生成 __about__.py ...
%PYTHON% scripts/gen_version.py
if %ERRORLEVEL% NEQ 0 (
    echo [ERROR] 生成版本文件失败，中止打包。
    if "%CI_MODE%"=="0" pause
    exit /b %ERRORLEVEL%
)

:: ── 步骤 2: 编译 onefile 可执行文件 ──
%PYTHON% -m nuitka ^
    --standalone ^
    --onefile ^
    --output-dir="%OUTDIR%" ^
    --windows-console-mode=attach ^
    --enable-plugin=pyside6 ^
    --include-module=app._resources ^
    --include-module=services.GameParams ^
    --include-package=meshoptimizer ^
    --output-filename=KorabliParagrams.exe ^
    main.py

if %ERRORLEVEL% NEQ 0 (
    echo.
    echo [! ERROR] Nuitka build failed.
    if "%CI_MODE%"=="0" pause
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
if "%CI_MODE%"=="0" timeout /t 3
exit