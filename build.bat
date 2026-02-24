@echo off
echo [1/3] Cleaning old build files...
rd /s /q build dist
del /q *.spec

echo [2/3] Starting PyInstaller (Bundling internal tools)...
pyinstaller --noconfirm --onefile --windowed ^
--add-data "wowsunpack.exe;." ^
--add-data "pfsunpack.exe;." ^
--add-data "msgunfmt.exe;." ^
--add-data "GameParams.py;." ^
--hidden-import="GameParams" ^
--name "WowsAnalyzer" ^
"MainUI.py"

:: Check if the previous command failed
if %ERRORLEVEL% NEQ 0 (
    echo.
    echo [! ERROR] Build failed. Please check the logs above.
    pause
    exit /b %ERRORLEVEL%
)

echo [3/3] Organizing distribution folder...
cd dist

echo.
echo Build Successful! Closing in 3 seconds...
timeout /t 3
exit