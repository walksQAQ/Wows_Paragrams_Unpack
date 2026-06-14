@echo off

set OUTDIR=release

if exist "%OUTDIR%" rd /s /q "%OUTDIR%"

python -m nuitka ^
--standalone ^
--onefile ^
--output-dir=%OUTDIR% ^
--windows-console-mode=disable ^
--enable-plugin=tk-inter ^
--include-data-file=wowsunpack.exe=wowsunpack.exe ^
--include-data-file=pfsunpack.exe=pfsunpack.exe ^
--include-data-file=pfsunpack2.exe=pfsunpack2.exe ^
--include-module=GameParams ^
--output-filename=WowsAnalyzer.exe ^
MainUI.py

copy /y config.json "%OUTDIR%\config.json"

rd /s /q "%OUTDIR%\MainUI.build" 2>nul
rd /s /q "%OUTDIR%\MainUI.dist" 2>nul
rd /s /q "%OUTDIR%\MainUI.onefile-build" 2>nul