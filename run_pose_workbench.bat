@echo off
setlocal
cd /d "%~dp0"
"%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe" -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\launch.ps1" -Mode workbench %*
set "POSE_EXIT=%ERRORLEVEL%"
if not "%POSE_EXIT%"=="0" pause
exit /b %POSE_EXIT%
