@echo off
set _CL_=/utf-8
set _LINK_=/utf-8
chcp 65001 >nul

set PYTHON="C:\Users\walks\AppData\Local\Programs\Python\Python313\python.exe"
set OUTDIR=release

if exist "%OUTDIR%" rd /s /q "%OUTDIR%"

python -m nuitka ^
--standalone ^
--onefile ^
--output-dir=%OUTDIR% ^
--windows-console-mode=disable ^
--enable-plugin=pyside6 ^
--include-data-file=tools/*.exe=tools/ ^
--include-module=services.GameParams ^
--output-filename=WowsAnalyzer.exe ^
main.py

rd /s /q "%OUTDIR%\main.build" 2>nul
rd /s /q "%OUTDIR%\main.dist" 2>nul
rd /s /q "%OUTDIR%\main.onefile-build" 2>nul