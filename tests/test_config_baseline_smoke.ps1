[CmdletBinding()]
param(
  [string]$BaseUrl = 'http://127.0.0.1:8765',
  [string]$StateDir = "$env:USERPROFILE\.wechat-ai"
)

$ErrorActionPreference = 'Stop'
$baseUri = [Uri]$BaseUrl
if (-not $baseUri.IsLoopback) { throw 'Smoke verification only permits a loopback BaseUrl.' }

function Get-LocalJson([string]$Path) {
  return Invoke-RestMethod -Method Get -Uri ($BaseUrl.TrimEnd('/') + $Path) -TimeoutSec 8
}

function Write-Status([string]$Name, [string]$Value) {
  Write-Output ("[ok] {0}: {1}" -f $Name, $Value)
}

$health = Get-LocalJson '/api/health'
if ($health.status -ne 'ok') { throw '/api/health did not report ok.' }
$status = Get-LocalJson '/api/status'
$runtime = Get-LocalJson '/api/runtime'
$config = Get-LocalJson '/api/config/status'
$providersResponse = Invoke-WebRequest -Method Get -Uri ($BaseUrl.TrimEnd('/') + '/api/providers') -TimeoutSec 8 -UseBasicParsing
$providerText = $providersResponse.Content

if ($status.activeWriter -eq $null -or -not $status.activeWriter.pid) {
  throw '/api/status did not expose an active writer pid.'
}
if ($runtime.settings -eq $null -or $runtime.status -eq $null) {
  throw '/api/runtime is missing its compatibility sections.'
}
if ($config.saved.reloadToken -eq $null -or $config.effective.reloadToken -eq $null) {
  throw '/api/config/status is missing saved/effective revisions.'
}
if ($config.health -notin @('healthy', 'pending_reload')) {
  throw "runtime config health is $($config.health)."
}
if ($providerText -match '(?i)"apiKey"\s*:|"api_key"\s*:') {
  throw 'provider API key field was returned by the local API.'
}

$legacyPath = Join-Path $StateDir 'siliconflow.json'
if (Test-Path -LiteralPath $legacyPath) {
  $legacy = Get-Content -LiteralPath $legacyPath -Raw | ConvertFrom-Json
  $secret = [string]$legacy.apiKey
  if ($secret -and $providerText.Contains($secret)) {
    throw 'configured provider secret was returned by the local API.'
  }
}

$daemonPid = [int]$status.activeWriter.pid
$daemonProcess = Get-CimInstance Win32_Process -Filter "ProcessId = $daemonPid" -ErrorAction SilentlyContinue
if (-not $daemonProcess) { throw "daemon pid $daemonPid is not running." }
if ($daemonProcess.CommandLine -notmatch '(?i)wechat_ai_daemon\.py') {
  throw "active writer pid $daemonPid is not the expected daemon process."
}

Write-Status '/api/health' $health.status
Write-Status 'daemon' ("pid {0}" -f $daemonPid)
Write-Status 'runtime config' ("health={0}; saved={1}; effective={2}" -f $config.health, $config.saved.reloadToken, $config.effective.reloadToken)
Write-Status 'providers' ("count={0}; secrets=redacted" -f @($providersResponse.Content | ConvertFrom-Json).providers.Count)
Write-Output 'Read-only configuration baseline smoke passed.'
