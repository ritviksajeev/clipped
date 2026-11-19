@echo off
rem Double-click this file to update clipped: it pulls the latest version,
rem installs it, rebuilds the app's UI, then starts clipped.
cd /d "%~dp0"
echo Updating clipped in %CD%
echo.
git pull || goto :fail
if not exist ".venv\Scripts\python.exe" (
  echo Creating the Python environment...
  python -m venv .venv || goto :fail
)
call ".venv\Scripts\activate.bat" || goto :fail
python -m pip install -e . || goto :fail
pushd frontend
call npm ci || (popd & goto :fail)
call npm run build || (popd & goto :fail)
popd
echo.
echo clipped is up to date. Starting it...
start "" ".venv\Scripts\pythonw.exe" -m clipped app
exit /b 0

:fail
echo.
echo Something went wrong above. Copy the messages and send them over.
pause
exit /b 1
