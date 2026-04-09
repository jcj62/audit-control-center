@echo off
setlocal

set "ROOT=%~dp0"
where wscript.exe >nul 2>nul
if %errorlevel%==0 (
    wscript.exe "%ROOT%Run Audit Control.vbs"
    goto :eof
)

if exist "%ROOT%\.venv\Scripts\python.exe" (
    "%ROOT%\.venv\Scripts\python.exe" "%ROOT%\start_app.py"
    goto :eof
)

where py >nul 2>nul
if %errorlevel%==0 (
    py -3 "%ROOT%\start_app.py"
    goto :eof
)

python "%ROOT%\start_app.py"

endlocal
