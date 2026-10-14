@echo off
setlocal
cd /d "%~dp0"
title Pharma Cost Simulator

if exist ".venv\Scripts\python.exe" goto check_environment

py -3.12 -c "import sys; sys.exit(0)" >nul 2>&1
if errorlevel 1 goto try_python
py -3.12 -m venv .venv
if errorlevel 1 goto setup_failed
goto check_environment

:try_python
python -c "import sys; sys.exit(0 if (3,10) <= sys.version_info[:2] < (3,14) else 1)" >nul 2>&1
if errorlevel 1 goto python_missing
python -m venv .venv
if errorlevel 1 goto setup_failed

:check_environment
".venv\Scripts\python.exe" -c "import PySide6; import sys; sys.exit(0 if PySide6.__version__ == '6.8.3' else 1)" >nul 2>&1
if not errorlevel 1 goto run_app
echo First-time setup: an Internet connection is required.
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 goto setup_failed

:run_app
".venv\Scripts\python.exe" run_app.py
if errorlevel 1 goto app_failed
exit /b 0

:python_missing
echo Python 3.12 is required for the easiest setup.
echo Install the Windows 64-bit version of Python 3.12, then try again.
echo During installation, select "Add python.exe to PATH".
echo Instructions: READ-ME-FIRST.txt
pause
exit /b 1

:setup_failed
echo Setup failed. Check your Internet connection and Python installation.
echo The error message above can help diagnose the problem.
pause
exit /b 1

:app_failed
echo The application could not run. Please share the error message above.
pause
exit /b 1
