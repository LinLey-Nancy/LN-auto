@echo off
rem Build the LN-auto installer: dist\LN-auto-v<version>-Setup.exe
setlocal
set "ROOT=%~dp0.."
if exist "%ROOT%\.venv\Scripts\python.exe" (
    "%ROOT%\.venv\Scripts\python.exe" "%~dp0build_installer.py" %*
) else (
    python "%~dp0build_installer.py" %*
)
endlocal
