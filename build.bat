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
if "%CI_MODE%"=="0" taskkill /f /im WowsKorabliDataViewer.exe 2>nul

set PYTHON=.venv\Scripts\python.exe
set OUTDIR=release

:: Force UTF-8 mode: gen_qrc.py etc. emit CJK text; CI pipes default cp1252 would
:: raise UnicodeEncodeError (chcp 65001 only changes console codepage, not pipes)
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8

:: Force-delete old exe if it is temporarily locked (antivirus etc.)
if exist "%OUTDIR%\WowsKorabliDataViewer.exe" del /f /q "%OUTDIR%\WowsKorabliDataViewer.exe" 2>nul

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

:: Step 1.6: build native D3D11 renderer DLL (release\wows_renderer.dll)
::   Required by the D3D11 viewport backend; a silent skip would produce a build
::   that always falls back to OpenGL, so failures abort the build. Set
::   SKIP_NATIVE_RENDERER=1 to build without it (e.g. no MSVC/CMake here).
echo [NATIVE] Building D3D11 renderer DLL ...
:: Drop a stale DLL first: a failed configure/build must never silently embed
:: an outdated renderer.
if exist "%OUTDIR%\wows_renderer.dll" del /f /q "%OUTDIR%\wows_renderer.dll" 2>nul
set CMAKE_EXE=
where cmake >nul 2>nul
if %ERRORLEVEL%==0 set CMAKE_EXE=cmake
if defined CMAKE_EXE goto :cmake_ready
set "VSWHERE=%ProgramFiles(x86)%\Microsoft Visual Studio\Installer\vswhere.exe"
set "VSROOT="
if exist "%VSWHERE%" for /f "usebackq delims=" %%I in (`"%VSWHERE%" -latest -products * -property installationPath`) do set "VSROOT=%%I"
if defined VSROOT if exist "%VSROOT%\Common7\IDE\CommonExtensions\Microsoft\CMake\CMake\bin\cmake.exe" set "CMAKE_EXE=%VSROOT%\Common7\IDE\CommonExtensions\Microsoft\CMake\CMake\bin\cmake.exe"
:cmake_ready
if not defined CMAKE_EXE goto :native_missing
"%CMAKE_EXE%" -S native -B native\build >nul
if %ERRORLEVEL% NEQ 0 goto :native_fail
"%CMAKE_EXE%" --build native\build --config Release >nul
if %ERRORLEVEL% NEQ 0 goto :native_fail
if not exist "%OUTDIR%\wows_renderer.dll" goto :native_fail
goto :native_done
:native_missing
echo [! ERROR] cmake not found - cannot build wows_renderer.dll.
goto :native_done
:native_fail
echo [! ERROR] native renderer build failed (native\build has the cmake log).
:native_done

:: Embed the DLL into the onefile payload (Nuitka extracts it next to the
:: compiled "renderer" package inside the onefile temp dir, which is where
:: renderer/api.py::_search_paths() looks for it at runtime).
set DLL_ARG=
if exist "%OUTDIR%\wows_renderer.dll" set DLL_ARG=--include-data-files=%OUTDIR%/wows_renderer.dll=wows_renderer.dll
if not defined DLL_ARG (
    if "%SKIP_NATIVE_RENDERER%"=="1" (
        echo [WARN] building WITHOUT wows_renderer.dll - 3D viewport will use OpenGL.
    ) else (
        echo [! ERROR] wows_renderer.dll missing - refusing to build without the D3D11 renderer.
        echo [! ERROR] Fix the native build, or set SKIP_NATIVE_RENDERER=1 to build anyway.
        if "%CI_MODE%"=="0" pause
        exit /b 1
    )
)

:: Compiler strategy: local and CI both use Nuitka default toolchain (MSVC).
:: Nuitka 2.x removed --mingw64 (MinGW) on Python 3.13+, so CI no longer
:: passes --mingw64; keeps --lto=no to reduce build time on CI runners.
set EXTRA_NUITKA_ARGS=
if "%CI_MODE%"=="1" set EXTRA_NUITKA_ARGS=--lto=no

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
    %DLL_ARG% ^
    --output-filename=WowsKorabliDataViewer.exe ^
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
