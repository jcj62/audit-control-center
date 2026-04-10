$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $root
$runDir = Join-Path $root ".run"
New-Item -ItemType Directory -Force -Path $runDir | Out-Null
$runtimeDir = if ($env:LOCALAPPDATA) {
    Join-Path $env:LOCALAPPDATA "AuditControlCenter"
} else {
    Join-Path $root "backend\\runtime"
}
New-Item -ItemType Directory -Force -Path $runtimeDir | Out-Null

$env:AUDIT_RUNTIME_DIR = $runtimeDir
$env:BOT_AUTH_DIR = Join-Path $runtimeDir "bot-auth"
$env:BOT_MEDIA_DIR = Join-Path $runtimeDir "media\\images"
$env:AUDIT_REPORTS_DIR = Join-Path $runtimeDir "reports"
$bindHost = if ($env:AUDIT_BIND_HOST) { $env:AUDIT_BIND_HOST } else { "0.0.0.0" }
$backendPort = if ($env:AUDIT_PORT) { [int]$env:AUDIT_PORT } else { 8000 }
$env:API_BASE_URL = "http://127.0.0.1:$backendPort"

function Get-LanIp {
    try {
        $route = Get-NetRoute -DestinationPrefix "0.0.0.0/0" -ErrorAction Stop |
            Sort-Object RouteMetric |
            Select-Object -First 1

        if ($route) {
            $address = Get-NetIPAddress -AddressFamily IPv4 -InterfaceIndex $route.InterfaceIndex -ErrorAction Stop |
                Where-Object {
                    $_.IPAddress -notlike "127.*" -and
                    $_.IPAddress -notlike "169.254.*"
                } |
                Select-Object -First 1

            if ($address) {
                return $address.IPAddress
            }
        }
    } catch {
    }

    try {
        $addresses = [System.Net.Dns]::GetHostAddresses([System.Net.Dns]::GetHostName()) |
            Where-Object {
                $_.AddressFamily -eq [System.Net.Sockets.AddressFamily]::InterNetwork -and
                $_.IPAddressToString -notlike "127.*" -and
                $_.IPAddressToString -notlike "169.254.*"
            }

        if ($addresses) {
            return $addresses[0].IPAddressToString
        }
    } catch {
    }

    return $null
}

$lanIp = Get-LanIp
$openHost = if ($lanIp) { $lanIp } else { "127.0.0.1" }
$openUrl = if ($env:AUDIT_OPEN_URL) { $env:AUDIT_OPEN_URL } else { "http://$openHost`:$backendPort" }

$pythonCmd = "python"

function Test-PythonModule([string]$pythonPath, [string]$moduleName) {
    try {
        $null = & $pythonPath -c "import $moduleName" 2>$null
        return $LASTEXITCODE -eq 0
    } catch {
        return $false
    }
}

$venvPython = Join-Path $root ".venv\Scripts\python.exe"
if ((Test-Path $venvPython) -and (Test-PythonModule $venvPython "uvicorn")) {
    $pythonCmd = $venvPython
} elseif (!(Test-PythonModule $pythonCmd "uvicorn")) {
    throw "No usable Python with uvicorn was found. Run 'Install Audit Control.bat' first."
}

function Test-RunningPid([string]$pidFile) {
    if (!(Test-Path $pidFile)) {
        return $false
    }

    $pidValue = Get-Content $pidFile -ErrorAction SilentlyContinue | Select-Object -First 1
    if (!$pidValue) {
        return $false
    }

    return $null -ne (Get-Process -Id $pidValue -ErrorAction SilentlyContinue)
}

function Test-Backend {
    try {
        $response = Invoke-WebRequest -UseBasicParsing "http://127.0.0.1:$backendPort/api/health" -TimeoutSec 2
        return $response.StatusCode -eq 200
    } catch {
        return $false
    }
}

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

function Test-BackendSupportsCurrentApi {
    try {
        Invoke-WebRequest -UseBasicParsing -Method Post -Uri "http://127.0.0.1:$backendPort/api/bot/claim" -Headers @{ "X-Bot-Session" = "probe" } -TimeoutSec 2 | Out-Null
        return $true
    } catch {
        $response = $_.Exception.Response
        if ($null -eq $response) {
            return $false
        }

        $statusCode = [int]$response.StatusCode
        return $statusCode -in @(200, 400, 409)
    }
}

function Stop-StaleBackendOnPort {
    if (!(Test-Backend)) {
        return
    }

    if (Test-BackendSupportsCurrentApi) {
        return
    }

    $pid = Get-PortOwnerPid $backendPort
    if ($pid) {
        taskkill /PID $pid /T /F | Out-Null
        Start-Sleep -Seconds 2
    }
}

function Test-AuthSession {
    $authDir = $env:BOT_AUTH_DIR
    if (!(Test-Path $authDir)) {
        return $false
    }

    $files = Get-ChildItem -Path $authDir -File -Force -ErrorAction SilentlyContinue
    return $files.Count -gt 0
}

function Start-BackendHidden {
    Stop-StaleBackendOnPort

    if (Test-Backend) {
        return
    }

    $stdoutLog = Join-Path $runDir "backend.stdout.log"
    $stderrLog = Join-Path $runDir "backend.stderr.log"
    $process = Start-Process -WindowStyle Hidden -FilePath $pythonCmd -ArgumentList @(
        "-m", "uvicorn", "backend.app.main:app", "--host", $bindHost, "--port", "$backendPort"
    ) -WorkingDirectory $root -RedirectStandardOutput $stdoutLog -RedirectStandardError $stderrLog -PassThru
    Set-Content -Path (Join-Path $runDir "backend.pid") -Value $process.Id

    for ($i = 0; $i -lt 15; $i++) {
        Start-Sleep -Seconds 1
        if (Test-Backend) {
            return
        }
    }

    throw "Backend did not start in time. Check .run\\backend.stderr.log"
}

function Start-BotHidden {
    $botDir = Join-Path $root "bot"
    $botPidFile = Join-Path $runDir "bot.pid"
    if (Test-RunningPid $botPidFile) {
        return
    }

    $stdoutLog = Join-Path $runDir "bot.stdout.log"
    $stderrLog = Join-Path $runDir "bot.stderr.log"
    $env:BOT_INSTANCE_ID = [guid]::NewGuid().Guid
    $process = Start-Process -WindowStyle Hidden -FilePath "node.exe" -ArgumentList @("index.js") -WorkingDirectory $botDir -RedirectStandardOutput $stdoutLog -RedirectStandardError $stderrLog -PassThru
    Set-Content -Path $botPidFile -Value $process.Id
}

function Reset-BotStateIfSessionMissing {
    if (Test-AuthSession) {
        return
    }

    try {
        Invoke-RestMethod -Method Post -Uri "http://127.0.0.1:$backendPort/api/bot/reset-state" -TimeoutSec 5 | Out-Null
    } catch {
    }
}

function Open-AppWindow {
    $edgePaths = @(
        "$env:ProgramFiles(x86)\Microsoft\Edge\Application\msedge.exe",
        "$env:ProgramFiles\Microsoft\Edge\Application\msedge.exe"
    )
    $chromePaths = @(
        "$env:ProgramFiles\Google\Chrome\Application\chrome.exe",
        "$env:ProgramFiles(x86)\Google\Chrome\Application\chrome.exe"
    )

    foreach ($browser in ($edgePaths + $chromePaths)) {
        if (Test-Path $browser) {
            Start-Process -FilePath $browser -ArgumentList "--app=$openUrl"
            return
        }
    }

    Start-Process $openUrl
}

Start-BackendHidden
Reset-BotStateIfSessionMissing
Start-BotHidden
Open-AppWindow
