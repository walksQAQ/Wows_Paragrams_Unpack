@echo off
echo [1/3] Cleaning old build files...
if exist build rd /s /q build
if exist dist rd /s /q dist
if exist *.spec del /q *.spec

echo [2/3] Starting PyInstaller...
pyinstaller --noconfirm --onefile --windowed ^
--add-data "wowsunpack.exe;." ^
--add-data "pfsunpack.exe;." ^
--add-data "GameParams.py;." ^
--hidden-import="GameParams" ^
--collect-all "customtkinter" ^
--name "WowsAnalyzer" ^
"MainUI.py"

if %ERRORLEVEL% NEQ 0 (
    echo.
    echo [! ERROR] Build failed.
    pause
    exit /b %ERRORLEVEL%
)

echo [3/3] Organizing distribution folder...
:: --- 核心修改：复制 config.json 到 dist 文件夹 ---
if exist "config.json" (
    copy /y "config.json" "dist\config.json"
    echo [OK] config.json copied to dist folder.
) else (
    echo [!] Warning: config.json not found, skipping copy.
)

echo Build Successful!
timeout /t 3
exit