@echo off
setlocal
cd /d "%~dp0"
title KJP Paper Trader

rem Find Python (the "py" launcher comes with the python.org installer).
set "PY="
where py >nul 2>nul && set "PY=py -3"
if not defined PY (where python >nul 2>nul && set "PY=python")
if not defined PY (
  echo Python was not found. Install it from https://www.python.org/downloads/
  echo and tick "Add python.exe to PATH" during setup.
  pause
  exit /b 1
)

if not exist ".venv\Scripts\python.exe" (
  echo First run: setting up a private Python environment. This takes a minute...
  %PY% -m venv .venv || goto :fail
)

".venv\Scripts\python.exe" -m pip install --disable-pip-version-check -q -r requirements.txt || goto :fail

if not exist "frontend\dist\index.html" (
  echo Building the website...
  pushd frontend
  call npm install || goto :fail
  call npm run build || goto :fail
  popd
)

".venv\Scripts\python.exe" backend\main.py
goto :eof

:fail
echo.
echo Something went wrong during setup. Copy the messages above and send them to Claude.
pause
exit /b 1
