[CmdletBinding()]
param(
  [string]$BaseUrl = 'http://127.0.0.1:8765',
  [string]$StateDir = "$env:USERPROFILE\.wechat-ai",
  [switch]$SendTest
)

$ErrorActionPreference = 'Stop'
$scriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$replyScript = Join-Path $scriptRoot 'wechat_ai_reply.py'

function Write-Check([string]$Name, [string]$Detail) {
  Write-Output ("[ok] {0}: {1}" -f $Name, $Detail)
}

function Invoke-LocalJson([string]$Path) {
  return Invoke-RestMethod -Method Get -Uri ($BaseUrl.TrimEnd('/') + $Path) -TimeoutSec 8
}

$baseUri = [Uri]$BaseUrl
if (-not $baseUri.IsLoopback) {
  throw 'Console verification only permits a loopback BaseUrl.'
}

$container = & docker ps --filter 'name=^/agent-wechat$' --format '{{.Names}} {{.Status}}'
if ($LASTEXITCODE -ne 0 -or -not ($container -match '^agent-wechat\s+Up')) {
  throw 'docker container agent-wechat is not running.'
}
Write-Check 'docker' $container.Trim()

$wechatRaw = & py -3.11 $replyScript status
if ($LASTEXITCODE -ne 0) {
  throw 'Unable to read WeChat login status.'
}
$wechat = $wechatRaw | ConvertFrom-Json
$loginText = $wechat.auth | ConvertTo-Json -Compress
if ($loginText -notmatch 'logged_in|authenticated|true') {
  throw "WeChat login is not ready: $loginText"
}
Write-Check 'login' $loginText

$activePath = Join-Path $StateDir 'daemon.active'
if (-not (Test-Path -LiteralPath $activePath)) {
  throw 'daemon.active is missing; the standalone daemon is not the active writer.'
}
$active = Get-Content -LiteralPath $activePath -Raw | ConvertFrom-Json
$daemon = Get-Process -Id ([int]$active.pid) -ErrorAction SilentlyContinue
if (-not $daemon) {
  throw "daemon pid $($active.pid) is not running."
}
Write-Check 'daemon' ("pid {0}" -f $active.pid)

$health = Invoke-LocalJson '/api/health'
if ($health.status -ne 'ok') { throw '/api/health did not report ok.' }
Write-Check '/api/health' $health.status

$apiStatus = Invoke-LocalJson '/api/status'
$runtime = Invoke-LocalJson '/api/runtime'
$configStatus = Invoke-LocalJson '/api/config/status'
$providersResponse = Invoke-WebRequest -Method Get -Uri ($BaseUrl.TrimEnd('/') + '/api/providers') -TimeoutSec 8 -UseBasicParsing
if ($apiStatus.activeWriter -eq $null -or -not $apiStatus.activeWriter.pid) { throw '/api/status did not expose an active writer.' }
if ($runtime.settings -eq $null -or $runtime.status -eq $null) { throw '/api/runtime compatibility sections are missing.' }
if ($configStatus.saved.reloadToken -eq $null -or $configStatus.effective.reloadToken -eq $null) { throw '/api/config/status revisions are missing.' }
if ($configStatus.health -notin @('healthy', 'pending_reload')) { throw "runtime config health is $($configStatus.health)." }
if ($providersResponse.Content -match '(?i)"apiKey"\s*:|"api_key"\s*:') { throw 'provider API key field was returned.' }
Write-Check '/api/status' ("active writer pid {0}" -f $apiStatus.activeWriter.pid)
Write-Check '/api/runtime' 'compatibility sections present'
Write-Check '/api/config/status' ("health {0}; saved {1}; effective {2}" -f $configStatus.health, $configStatus.saved.reloadToken, $configStatus.effective.reloadToken)
Write-Check '/api/providers' 'credentials redacted'

$capabilities = Invoke-LocalJson '/api/capabilities'
Write-Check '/api/capabilities' ($capabilities | ConvertTo-Json -Compress)

$chatPage = Invoke-LocalJson '/api/chats?limit=1'
$firstChat = @($chatPage.chats)[0]
if (-not $firstChat.id) { throw '/api/chats returned no verifiable chat.' }
Write-Check '/api/chats' ("first chat id {0}" -f $firstChat.id)

$encodedChatId = [Uri]::EscapeDataString([string]$firstChat.id)
$messagePage = Invoke-LocalJson ("/api/chats/{0}/messages?limit=1" -f $encodedChatId)
Write-Check 'message page' ("{0} records" -f @($messagePage.messages).Count)

$shellResponse = Invoke-WebRequest -Method Get -Uri ($BaseUrl.TrimEnd('/') + '/conversations') -TimeoutSec 8 -UseBasicParsing
if ($shellResponse.StatusCode -ne 200 -or $shellResponse.Content -notmatch 'wechat-shell') {
  throw '/conversations desktop shell is unavailable.'
}
Write-Check '/conversations' 'desktop shell loaded'

if ($SendTest) {
  $testFile = Join-Path ([IO.Path]::GetTempPath()) ("wechat-console-smoke-{0}.txt" -f [Guid]::NewGuid().ToString('N'))
  try {
    Set-Content -LiteralPath $testFile -Value ("本地控制台验收测试 {0}" -f (Get-Date -Format o)) -Encoding utf8
    $sendResult = & py -3.11 $replyScript send --chat filehelper --text-file $testFile --send
    if ($LASTEXITCODE -ne 0 -or ($sendResult -join "`n") -notmatch '"sent"\s*:\s*true') {
      throw 'filehelper send smoke test was not verified.'
    }
    Write-Check 'filehelper send' 'verified'
  }
  finally {
    Remove-Item -LiteralPath $testFile -Force -ErrorAction SilentlyContinue
  }
}
else {
  Write-Output '[skip] filehelper send: pass -SendTest to enable the only outbound smoke test.'
}

Write-Output 'WeChat console verification passed.'
