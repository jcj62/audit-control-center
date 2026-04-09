@echo off
setlocal

set "ROOT=%~dp0"
where wscript.exe >nul 2>nul
if %errorlevel%==0 (
    wscript.exe "%ROOT%Stop Audit Control.vbs"
    goto :eof
)

if exist "%ROOT%\.venv\Scripts\python.exe" (
    "%ROOT%\.venv\Scripts\python.exe" "%ROOT%\stop_app.py"
    goto :eof
)

where py >nul 2>nul
if %errorlevel%==0 (
    py -3 "%ROOT%\stop_app.py"
    goto :eof
)

python "%ROOT%\stop_app.py"

endlocal
