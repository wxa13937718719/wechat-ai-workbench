$ErrorActionPreference = 'Stop'
$script = Join-Path $PSScriptRoot '..\scripts\bootstrap_wechat_ai.ps1'
$temporaryState = Join-Path ([IO.Path]::GetTempPath()) ('wechat-bootstrap-test-' + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $temporaryState | Out-Null
try {
  $output = & $script -Config (Join-Path $temporaryState 'daemon.json') -DryRun -SkipDocker -SkipContainer -SkipLogin
  if (-not $?) { throw 'bootstrap dry-run failed' }
  if (($output | Out-String) -notmatch 'dry-run: ensure daemon') { throw 'daemon verification missing' }
  if (($output | Out-String) -notmatch 'dry-run: ensure console') { throw 'console verification missing' }
  if (@(Get-ChildItem -LiteralPath $temporaryState -Force).Count -ne 0) { throw 'dry-run must not create state, logs or login files' }
} finally {
  $resolvedTestPath = [IO.Path]::GetFullPath($temporaryState)
  $resolvedTempRoot = [IO.Path]::GetFullPath([IO.Path]::GetTempPath())
  if ($resolvedTestPath.StartsWith($resolvedTempRoot, [StringComparison]::OrdinalIgnoreCase) -and
      [IO.Path]::GetFileName($resolvedTestPath).StartsWith('wechat-bootstrap-test-')) {
    Remove-Item -LiteralPath $resolvedTestPath -Recurse -Force
  }
}
Write-Output 'bootstrap isolated dry-run ok'
