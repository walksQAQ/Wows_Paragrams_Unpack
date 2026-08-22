@echo off
set _CL_=/utf-8
chcp 65001 >nul

:: CI mode: set CI_MODE=1 to skip local D: redirect and pause (for GitHub Actions)
if not defined CI_MODE set CI_MODE=0

:: 0. Redirect Nuitka build cache/temp to D: (avoid C: usage; local builds only)
if "%CI_MODE%"=="0" (
    set NUITKA_CACHE_DIR=D:\nuitka_cache
    set TMPDIR=D:\nuitka_tmp
    set TEMP=D:\nuitka_tmp
    set TMP=D:\nuitka_tmp
    if not exist "D:\nuitka_cache" mkdir "D:\nuitka_cache"
    if not exist "D:\nuitka_tmp" mkdir "D:\nuitka_tmp"
)

:: Kill old running program to avoid file-lock Access is denied
if "%CI_MODE%"=="0" taskkill /f /im KorabliParagrams.exe 2>nul

set PYTHON=.venv\Scripts\python.exe
set OUTDIR=release

:: Force UTF-8 mode: gen_qrc.py etc. emit CJK text; CI pipes default cp1252 would
:: raise UnicodeEncodeError (chcp 65001 only changes console codepage, not pipes)
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8

:: Force-delete old exe if it is temporarily locked (antivirus etc.)
if exist "%OUTDIR%\KorabliParagrams.exe" del /f /q "%OUTDIR%\KorabliParagrams.exe" 2>nul

:: Step 1: generate and compile Qt resources (QRC -> _resources.py)
echo [QRC] Generating resources.qrc ...
%PYTHON% scripts/gen_qrc.py
if %ERRORLEVEL% NEQ 0 (
    echo [! ERROR] QRC generation failed
    if "%CI_MODE%"=="0" pause
    exit /b %ERRORLEVEL%
)
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
if %ERRORLEVEL% NEQ 0 (
    echo [! ERROR] QRC compile failed
    if "%CI_MODE%"=="0" pause
    exit /b %ERRORLEVEL%
)
echo [QRC] resources compiled.

:: Step 1.5: generate version file from Git tag (before Nuitka)
echo [VERSION] Generating __about__.py from Git tag ...
%PYTHON% scripts/gen_version.py
if %ERRORLEVEL% NEQ 0 (
    echo [ERROR] version file generation failed, aborting.
    if "%CI_MODE%"=="0" pause
    exit /b %ERRORLEVEL%
)

:: Compiler strategy: local keeps Nuitka default toolchain (MSVC, known good);
:: CI uses MinGW gcc + disables LTO (MSVC full compile is slow on CI runners)
set EXTRA_NUITKA_ARGS=
if "%CI_MODE%"=="1" set EXTRA_NUITKA_ARGS=--mingw64 --lto=no

:: Step 2: compile onefile executable
%PYTHON% -m nuitka ^
    --standalone ^
    --onefile ^
    %EXTRA_NUITKA_ARGS% ^
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
    echo.
    echo [! ERROR] Nuitka build failed.
    if "%CI_MODE%"=="0" pause
    exit /b %ERRORLEVEL%
)

:: Copy config.json next to exe (local only; CI handled by build_ci.bat)
if "%CI_MODE%"=="0" (
    if exist "config.json" (
        copy /y "config.json" "%OUTDIR%\config.json" >nul
        echo [OK] config.json deployed to external release dir.
    ) else (
        echo [WARN] config.json template not found; default config auto-created on first run.
    )
)

:: Clean up Nuitka intermediate cache folders
rd /s /q "%OUTDIR%\main.build" 2>nul
rd /s /q "%OUTDIR%\main.dist" 2>nul
rd /s /q "%OUTDIR%\main.onefile-build" 2>nul

echo Build Successful!
if "%CI_MODE%"=="0" timeout /t 3
exit
