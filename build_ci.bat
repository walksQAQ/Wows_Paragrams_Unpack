@echo off
set _CL_=/utf-8
chcp 65001 >nul

:: ============================================================
:: GitHub Actions dedicated clean build script
::   Only job: produce release\WowsKorabliDataViewer.exe for Release upload.
::   No local-only steps (D: temp redirect, taskkill old process,
::   config.json copy, pause, timeout); decoupled from build.bat (local).
::   Invoked by: Build exe step in .github/workflows/release.yml
:: ============================================================

set PYTHON=.venv\Scripts\python.exe
set OUTDIR=release

:: Force UTF-8 mode: CI pipes default cp1252 would raise UnicodeEncodeError
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8

:: Step 1: generate and compile Qt resources (QRC -> _resources.py)
echo [QRC] Generating resources.qrc ...
%PYTHON% scripts/gen_qrc.py
if %ERRORLEVEL% NEQ 0 exit /b %ERRORLEVEL%
echo [QRC] Compiling _resources.py ...
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
echo [QRC] resources compiled.

:: Step 1.5: generate version file from Git tag (incl. pre-release version)
echo [VERSION] Generating __about__.py from Git tag ...
%PYTHON% scripts/gen_version.py
if %ERRORLEVEL% NEQ 0 exit /b %ERRORLEVEL%

:: Step 2: compile onefile executable
:: CI uses MinGW gcc (--mingw64) + disabled LTO (--lto=no) to avoid slow
:: MSVC full compile on runners; --assume-yes-for-downloads lets Nuitka
:: auto-download gcc etc.
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
    --output-filename=WowsKorabliDataViewer.exe ^
    main.py

if %ERRORLEVEL% NEQ 0 (
    echo [! ERROR] Nuitka build failed.
    exit /b %ERRORLEVEL%
)

:: Clean up Nuitka intermediate cache folders (keep exe in %OUTDIR%)
rd /s /q "%OUTDIR%\main.build" 2>nul
rd /s /q "%OUTDIR%\main.dist" 2>nul
rd /s /q "%OUTDIR%\main.onefile-build" 2>nul

echo Build Successful!
exit /b 0
