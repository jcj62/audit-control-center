@echo off
setlocal

set "ROOT=%~dp0"
cd /d "%ROOT%"
set "PYTHON_CMD=python"

if exist ".venv\Scripts\python.exe" (
  ".venv\Scripts\python.exe" -c "import uvicorn" >nul 2>nul
  if not errorlevel 1 (
    set "PYTHON_CMD=.venv\Scripts\python.exe"
  )
)

echo Installing Python dependencies...
call %PYTHON_CMD% -m pip install -r requirements.txt
if errorlevel 1 goto :fail

echo Installing bot dependencies...
cd /d "%ROOT%bot"
call npm install
if errorlevel 1 goto :fail

echo.
echo Installation complete.
echo You can now double-click "Run Audit Control.bat"
goto :end

:fail
echo.
echo Installation failed.
exit /b 1

:end
endlocal
