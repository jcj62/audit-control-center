@echo off
setlocal

set "ROOT=%~dp0"
wscript.exe "%ROOT%Run Audit Control.vbs"

endlocal
