@echo off
setlocal

set "ROOT=%~dp0"
wscript.exe "%ROOT%Stop Audit Control.vbs"

endlocal
