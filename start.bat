@echo off
if defined WINDOW_AUTO_HIDDEN goto hidden_start
start "" wscript.exe "%~dp0start.vbs" %*
exit /b 0

:hidden_start
setlocal
cd /d "%~dp0"

if not defined WINDOW_AUTO_HIDDEN goto main
if defined WINDOW_AUTO_LOGGING goto main
set "WINDOW_AUTO_LOGGING=1"
if not exist "debug" mkdir "debug"
call "%~f0" %* > "debug\startup.log" 2>&1
exit /b %errorlevel%

:main
set "VENV_PY=.venv\Scripts\python.exe"
set "GUI_EXE=.venv\Scripts\window-auto-gui.exe"

if exist "%VENV_PY%" goto check_environment

echo [Window Auto] Creating the Python 3.12 environment...
py -3.12 -c "import sys; raise SystemExit(0 if sys.version_info[:2] == (3, 12) else 1)" >nul 2>&1
if not errorlevel 1 (
    py -3.12 -m venv ".venv"
    goto check_created
)

python -c "import sys; raise SystemExit(0 if sys.version_info[:2] == (3, 12) else 1)" >nul 2>&1
if errorlevel 1 goto python_missing
python -m venv ".venv"

:check_created
if not exist "%VENV_PY%" goto venv_failed

:check_environment
"%VENV_PY%" -c "import sys; assert sys.version_info[:2] == (3, 12); import maa; import PySide6; import window_auto.gui.app" >nul 2>&1
if not errorlevel 1 goto launch

echo [Window Auto] Installing required dependencies...
"%VENV_PY%" -m pip install --disable-pip-version-check -e ".[gui]"
if errorlevel 1 goto install_failed

:launch
if not exist "%GUI_EXE%" goto install_failed
echo [Window Auto] Starting...
"%GUI_EXE%" %*
if errorlevel 1 goto run_failed
exit /b 0

:python_missing
echo.
echo [Window Auto] Python 3.12 was not found.
echo Install 64-bit Python 3.12, then run this file again.
goto failed

:venv_failed
echo.
echo [Window Auto] Failed to create the .venv environment.
goto failed

:install_failed
echo.
echo [Window Auto] Failed to install the project dependencies.
goto failed

:run_failed
echo.
echo [Window Auto] The application exited with an error.

:failed
echo.
if defined WINDOW_AUTO_HIDDEN exit /b 1
pause
exit /b 1
