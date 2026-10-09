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

:: Step 1.6: build native D3D11 renderer DLL (release\wows_renderer.dll)
::   MANDATORY for releases: the D3D11 viewport backend loads this DLL at
::   runtime (see renderer/api.py), so a silent skip would ship an exe that
::   always falls back to OpenGL. Every failure below aborts the release.
echo [NATIVE] Building D3D11 renderer DLL ...
:: Drop a stale DLL first: a failed configure/build must never silently embed
:: an outdated renderer (fresh CI checkouts have none, reused ones may).
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
"%CMAKE_EXE%" -S native -B native\build
if %ERRORLEVEL% NEQ 0 goto :native_fail
"%CMAKE_EXE%" --build native\build --config Release
if %ERRORLEVEL% NEQ 0 goto :native_fail
if not exist "%OUTDIR%\wows_renderer.dll" goto :native_fail
goto :native_done
:native_missing
echo [! ERROR] cmake not found - cannot build wows_renderer.dll; release aborted.
exit /b 1
:native_fail
echo [! ERROR] native renderer build failed (see cmake output above); release aborted.
exit /b 1
:native_done

:: Embed the DLL into the onefile payload. Nuitka extracts it into the onefile
:: temp dir next to the compiled "renderer" package, which is exactly where
:: renderer/api.py::_search_paths() looks for it at runtime - this is what makes
:: the released exe use the D3D11 backend instead of the OpenGL fallback.
set DLL_ARG=
if exist "%OUTDIR%\wows_renderer.dll" set DLL_ARG=--include-data-files=%OUTDIR%/wows_renderer.dll=wows_renderer.dll
if not defined DLL_ARG (
    echo [! ERROR] refusing to build a release without the D3D11 renderer DLL.
    exit /b 1
)

:: Step 2: compile onefile executable
:: Nuitka 2.x removed --mingw64 (MinGW) support on Python 3.13+, so CI now
:: uses the default MSVC toolchain (windows-latest ships VS Build Tools).
:: --lto=no keeps build time down; --assume-yes-for-downloads lets Nuitka
:: auto-download MSVC components if not already present.
%PYTHON% -m nuitka ^
    --standalone ^
    --onefile ^
    --lto=no ^
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
    echo [! ERROR] Nuitka build failed.
    exit /b %ERRORLEVEL%
)

:: Clean up Nuitka intermediate cache folders (keep exe in %OUTDIR%)
rd /s /q "%OUTDIR%\main.build" 2>nul
rd /s /q "%OUTDIR%\main.dist" 2>nul
rd /s /q "%OUTDIR%\main.onefile-build" 2>nul

echo Build Successful!
exit /b 0
