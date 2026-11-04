param(
  [switch]$DryRun,
  [switch]$SkipDocker,
  [switch]$SkipContainer,
  [switch]$SkipLogin,
  [switch]$SkipDaemon,
  [switch]$SkipConsole,
  [string]$Config = ""
)

$ErrorActionPreference = "Stop"
if (-not $Config) {
  $baseStateDir = if ($env:WECHAT_AI_STATE_DIR) { $env:WECHAT_AI_STATE_DIR } else { Join-Path $env:USERPROFILE '.wechat-ai' }
  $Config = Join-Path $baseStateDir 'daemon.json'
}
$Config = [IO.Path]::GetFullPath($Config)
$stateDir = Split-Path -Parent $Config
if (-not $DryRun) { New-Item -ItemType Directory -Force -Path $stateDir | Out-Null }
$log = Join-Path $stateDir "bootstrap.log"
$statusPath = Join-Path $stateDir "login-status.json"
$heartbeatPath = Join-Path $stateDir "bootstrap.heartbeat"

function Write-BootstrapLog($message) {
  $line = "$(Get-Date -Format o) $message"
  if (-not $DryRun) { Add-Content -Path $log -Value $line -Encoding utf8 }
  Write-Output $line
}

function Write-LoginStatus($status) {
  if ($DryRun) { return }
  $payload = @{ status = $status; updatedAt = (Get-Date -Format o) } | ConvertTo-Json
  Set-Content -Path $statusPath -Value $payload -Encoding utf8
}

function Write-BootstrapHeartbeat() {
  if ($DryRun) { return }
  Set-Content -Path $heartbeatPath -Value (Get-Date -Format o) -Encoding utf8
}

function Read-DaemonConfig {
  if (Test-Path $Config) {
    return Get-Content $Config -Raw | ConvertFrom-Json
  }
  return [pscustomobject]@{}
}

function Test-DockerReady {
  docker info --format '{{.ServerVersion}}' 2>$null | Out-Null
  return $LASTEXITCODE -eq 0
}

function Start-DockerIfNeeded($timeoutSeconds) {
  if ($SkipDocker -or (Test-DockerReady)) { return }
  if ($DryRun) {
    Write-BootstrapLog "dry-run: docker desktop start --detach --timeout $timeoutSeconds"
    return
  }
  docker desktop start --detach --timeout $timeoutSeconds | Out-Null
  $deadline = (Get-Date).AddSeconds($timeoutSeconds)
  while ((Get-Date) -lt $deadline) {
    if (Test-DockerReady) { return }
    Start-Sleep -Seconds 5
  }
  throw "Docker did not become ready within $timeoutSeconds seconds"
}

function Test-ContainerReady {
  $status = wx status 2>&1 | Out-String
  return $status -match 'Container: up' -and $status -match 'Server: reachable'
}

function Start-ContainerIfNeeded($timeoutSeconds) {
  if ($SkipContainer -or (Test-ContainerReady)) { return }
  if ($DryRun) {
    Write-BootstrapLog "dry-run: wx up"
    return
  }
  wx up | Out-Null
  $deadline = (Get-Date).AddSeconds($timeoutSeconds)
  while ((Get-Date) -lt $deadline) {
    if (Test-ContainerReady) { return }
    Start-Sleep -Seconds 5
  }
  throw "agent-wechat container did not become ready within $timeoutSeconds seconds"
}

function Test-LoggedIn {
  $auth = wx auth status 2>&1 | Out-String
  return $auth -match 'logged in'
}

function Start-QrLogin($timeoutSeconds, $imagePath) {
  if ($SkipLogin) { return $true }
  if ($DryRun) {
    Write-LoginStatus 'login_qr_pending'
    Write-BootstrapLog "dry-run: start QR login"
    return $false
  }
  $authJob = Start-Job -ScriptBlock { param($timeout) wx auth login --timeout $timeout } -ArgumentList $timeoutSeconds
  try {
    $deadline = (Get-Date).AddSeconds($timeoutSeconds)
    while ((Get-Date) -lt $deadline) {
      if (Test-LoggedIn) {
        Write-LoginStatus 'logged_in'
        if (Test-Path $imagePath) { Remove-Item $imagePath -Force }
        return $true
      }
      wx screenshot $imagePath 2>$null | Out-Null
      if (Test-Path $imagePath) {
        Write-LoginStatus 'login_qr_pending'
        Invoke-Item $imagePath
        Start-Sleep -Seconds 10
        if (Test-Path $imagePath) { Remove-Item $imagePath -Force }
      }
      Start-Sleep -Seconds 2
    }
    Write-LoginStatus 'logged_out'
    return $false
  } finally {
    if (Get-Job -Id $authJob.Id -ErrorAction SilentlyContinue) {
      Remove-Job $authJob -Force -ErrorAction SilentlyContinue
    }
  }
}

function Resolve-Pythonw {
  $preferredPythonw = Join-Path $env:LOCALAPPDATA 'Programs\Python\Python311\pythonw.exe'
  $pythonw = Get-Command pythonw.exe -ErrorAction SilentlyContinue
  $venvPythonw = Join-Path (Split-Path -Parent $PSScriptRoot) '.venv\Scripts\pythonw.exe'
  if ($env:VIRTUAL_ENV -and (Test-Path (Join-Path $env:VIRTUAL_ENV 'Scripts\pythonw.exe'))) { return (Join-Path $env:VIRTUAL_ENV 'Scripts\pythonw.exe') }
  if (Test-Path $venvPythonw) { return $venvPythonw }
  if (Test-Path $preferredPythonw) { return $preferredPythonw }
  if ($pythonw) { return $pythonw.Source }
  return 'python.exe'
}

function Start-HiddenPython($scriptPath, $arguments) {
  $psi = New-Object System.Diagnostics.ProcessStartInfo
  $psi.FileName = Resolve-Pythonw
  $psi.Arguments = '"' + $scriptPath + '" ' + $arguments
  $psi.UseShellExecute = $false
  $psi.CreateNoWindow = $true
  $psi.WindowStyle = [System.Diagnostics.ProcessWindowStyle]::Hidden
  return [System.Diagnostics.Process]::Start($psi)
}

function Test-ExpectedPythonProcess($processId, $scriptPath) {
  if (-not $processId) { return $false }
  $process = Get-CimInstance Win32_Process -Filter "ProcessId = $([int]$processId)" -ErrorAction SilentlyContinue
  if (-not $process) { return $false }
  $isPython = [IO.Path]::GetFileName($process.ExecutablePath) -match '^python(w)?\.exe$'
  return $isPython -and $process.CommandLine.Contains($scriptPath, [StringComparison]::OrdinalIgnoreCase)
}

function Ensure-DaemonProcess($daemonConfig, $timeoutSeconds = 15) {
  if ($SkipDaemon) { return }
  if ($DryRun) {
    Write-BootstrapLog 'dry-run: ensure daemon process and writer lock'
    return
  }
  $daemonScript = Join-Path $PSScriptRoot 'wechat_ai_daemon.py'
  $activePath = Join-Path (Split-Path -Parent $daemonConfig) 'daemon.active'
  if (Test-Path $activePath) {
    try { $activePid = [int]((Get-Content $activePath -Raw | ConvertFrom-Json).pid) } catch { $activePid = 0 }
    if (Test-ExpectedPythonProcess $activePid $daemonScript) {
      Write-BootstrapLog "daemon already healthy (pid $activePid)"
      return
    }
    Remove-Item $activePath -Force -ErrorAction SilentlyContinue
  }
  $process = Start-HiddenPython $daemonScript ('--config "' + $daemonConfig + '"')
  $deadline = (Get-Date).AddSeconds($timeoutSeconds)
  while ((Get-Date) -lt $deadline) {
    if ($process.HasExited) { break }
    if (Test-Path $activePath) {
      try { $activePid = [int]((Get-Content $activePath -Raw | ConvertFrom-Json).pid) } catch { $activePid = 0 }
      if ($activePid -eq $process.Id -and (Test-ExpectedPythonProcess $activePid $daemonScript)) {
        Write-BootstrapLog "daemon verified (pid $activePid)"
        return
      }
    }
    Start-Sleep -Milliseconds 250
  }
  if (-not $process.HasExited) { $process.Kill() }
  throw "daemon failed to acquire its writer lock within $timeoutSeconds seconds"
}

$configJson = Read-DaemonConfig
$dockerTimeout = if ($configJson.dockerStartTimeoutSeconds) { [int]$configJson.dockerStartTimeoutSeconds } else { 180 }
$containerTimeout = if ($configJson.containerStartTimeoutSeconds) { [int]$configJson.containerStartTimeoutSeconds } else { 120 }
$qrTimeout = if ($configJson.qrLoginTimeoutSeconds) { [int]$configJson.qrLoginTimeoutSeconds } else { 300 }
$qrRetries = if ($configJson.qrMaxRetries) { [int]$configJson.qrMaxRetries } else { 3 }
$qrImage = if ($configJson.qrImagePath) { [Environment]::ExpandEnvironmentVariables($configJson.qrImagePath) } else { Join-Path $stateDir 'login-qr.png' }

Start-DockerIfNeeded $dockerTimeout
Start-ContainerIfNeeded $containerTimeout
Write-BootstrapHeartbeat

if (-not $SkipLogin) {
  if (-not (Test-LoggedIn)) {
    $attempt = 0
    while ($attempt -lt $qrRetries -and -not (Test-LoggedIn)) {
      $attempt += 1
      $loginOk = Start-QrLogin $qrTimeout $qrImage
      if ($loginOk) { break }
    }
    if (-not (Test-LoggedIn) -and -not $DryRun) {
      throw "WeChat login was not completed after $qrRetries attempts"
    }
  } else {
    Write-LoginStatus 'logged_in'
  }
} else {
  Write-LoginStatus 'logged_out'
}

Ensure-DaemonProcess $Config
Write-BootstrapHeartbeat

function Test-ConsoleHealth($url) {
  try {
    $result = Invoke-RestMethod -Uri $url -TimeoutSec 2
    return $result.status -eq 'ok'
  } catch {
    return $false
  }
}

function Ensure-ConsoleProcess($daemonConfig, $timeoutSeconds = 15) {
  if ($SkipConsole) { return }
  if ($DryRun) {
    Write-BootstrapLog 'dry-run: ensure console process and HTTP health'
    return
  }
  $consoleScript = Join-Path $PSScriptRoot 'wechat_ai_console.py'
  $consoleStateDir = Split-Path -Parent $daemonConfig
  $pidPath = Join-Path $consoleStateDir 'console.pid'
  $healthUrl = 'http://127.0.0.1:8765/api/health'
  if (Test-ConsoleHealth $healthUrl) {
    Write-BootstrapLog 'console already healthy on http://127.0.0.1:8765'
    return
  }
  if (Test-Path $pidPath) {
    try { $oldPid = [int](Get-Content $pidPath -Raw) } catch { $oldPid = 0 }
    if (Test-ExpectedPythonProcess $oldPid $consoleScript) {
      Stop-Process -Id $oldPid -Force -ErrorAction SilentlyContinue
    }
    Remove-Item $pidPath -Force -ErrorAction SilentlyContinue
  }
  $args = '--state-dir "' + $consoleStateDir + '" --host 127.0.0.1 --port 8765'
  $process = Start-HiddenPython $consoleScript $args
  Set-Content -Path $pidPath -Value $process.Id -Encoding ascii
  $deadline = (Get-Date).AddSeconds($timeoutSeconds)
  while ((Get-Date) -lt $deadline) {
    if ($process.HasExited) { break }
    if (Test-ConsoleHealth $healthUrl) {
      Write-BootstrapLog "console verified on http://127.0.0.1:8765 (pid $($process.Id))"
      return
    }
    Start-Sleep -Milliseconds 250
  }
  if (-not $process.HasExited) { $process.Kill() }
  Remove-Item $pidPath -Force -ErrorAction SilentlyContinue
  throw "console failed HTTP health check within $timeoutSeconds seconds"
}

Ensure-ConsoleProcess $Config
