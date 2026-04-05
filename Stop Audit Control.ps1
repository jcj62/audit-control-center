$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$runDir = Join-Path $root ".run"

function Get-PortOwnerPid([int]$port) {
    $line = netstat -ano | Select-String "127.0.0.1:$port" | Select-String "LISTENING" | Select-Object -First 1
    if (!$line) {
        return $null
    }

    $parts = ($line.ToString() -split "\s+") | Where-Object { $_ }
    if ($parts.Count -lt 5) {
        return $null
    }

    return $parts[-1]
}

foreach ($name in @("bot.pid", "backend.pid")) {
    $pidFile = Join-Path $runDir $name
    if (!(Test-Path $pidFile)) {
        continue
    }

    $pidValue = Get-Content $pidFile -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($pidValue) {
        taskkill /PID $pidValue /T /F | Out-Null
    }

    Remove-Item $pidFile -Force -ErrorAction SilentlyContinue
}

$backendPortPid = Get-PortOwnerPid 8000
if ($backendPortPid) {
    taskkill /PID $backendPortPid /T /F | Out-Null
}
