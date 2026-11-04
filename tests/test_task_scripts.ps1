$script = Join-Path $PSScriptRoot '..\scripts\install-wechat-ai-task.ps1'
$output = & $script -DryRun
if (-not $?) { throw 'task install dry-run failed' }
if (($output | Out-String) -notmatch 'desktop shortcut') {
  throw 'desktop shortcut dry-run missing'
}
$source = Get-Content (Join-Path $PSScriptRoot '..\scripts\install-wechat-ai-task.ps1') -Raw
if ($source -notmatch 'System32\\WindowsPowerShell\\v1\.0\\powershell\.exe') {
  throw 'startup launcher must use an absolute Windows PowerShell path'
}
if ($source -notmatch 'ExecutionPolicy Bypass') {
  throw 'startup launcher must bypass restrictive execution policy for its own script'
}
if ($source -notmatch 'desktopLauncher') {
  throw 'desktop shortcut must use a launcher that also bootstraps the daemon'
}
if ($source -notmatch 'wscript\.exe') {
  throw 'desktop shortcut must launch the hidden desktop bootstrap wrapper'
}
Write-Output 'task install dry-run ok'
