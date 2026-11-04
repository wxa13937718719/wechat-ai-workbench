param([switch]$DryRun)
$runKey = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Run'
$valueName = 'WeChat AI Reply Daemon'
$launcher = Join-Path $PSScriptRoot 'wechat_ai_launcher.vbs'
if ($DryRun) {
  Write-Output "dry-run: remove $runKey\$valueName"
  return
}
Remove-ItemProperty -Path $runKey -Name $valueName -ErrorAction SilentlyContinue
if (Test-Path $launcher) { Remove-Item $launcher -Force }
Write-Output "startup registry entry removed: $valueName"
