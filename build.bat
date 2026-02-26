@echo off
echo [1/3] Cleaning old build files...
if exist build rd /s /q build
if exist dist rd /s /q dist
if exist *.spec del /q *.spec

echo [2/3] Starting PyInstaller...
:: 使用 --collect-all 代替手动寻找路径，这更安全且不容易出错
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
echo Build Successful!
timeout /t 3
exit