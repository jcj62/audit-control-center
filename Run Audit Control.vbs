Set shell = CreateObject("WScript.Shell")
scriptPath = CreateObject("Scripting.FileSystemObject").GetParentFolderName(WScript.ScriptFullName)
command = "powershell -NoProfile -ExecutionPolicy Bypass -Command " & Chr(34) & _
    "$root = '" & Replace(scriptPath, "'", "''") & "'; " & _
    "$venv = Join-Path $root '.venv\Scripts\python.exe'; " & _
    "if (Test-Path $venv) { & $venv (Join-Path $root 'start_app.py') } " & _
    "elseif (Get-Command py -ErrorAction SilentlyContinue) { & py -3 (Join-Path $root 'start_app.py') } " & _
    "else { & python (Join-Path $root 'start_app.py') }" & Chr(34)
shell.Run command, 0, False
