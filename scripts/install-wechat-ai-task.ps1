param([switch]$DryRun)
$runKey = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Run'
$valueName = 'WeChat AI Reply Daemon'
$launcher = Join-Path $PSScriptRoot 'wechat_ai_launcher.vbs'
$desktopLauncher = Join-Path $PSScriptRoot 'wechat_ai_desktop_launcher.vbs'
$bootstrap = Join-Path $PSScriptRoot 'bootstrap_wechat_ai.ps1'
$desktopScript = Join-Path $PSScriptRoot 'wechat_ai_desktop.py'
$preferredPythonw = Join-Path $env:LOCALAPPDATA 'Programs\Python\Python311\pythonw.exe'
$pythonw = Get-Command pythonw.exe -ErrorAction SilentlyContinue
$venvPythonw = Join-Path (Split-Path -Parent $PSScriptRoot) '.venv\Scripts\pythonw.exe'
$desktopExe = if (Test-Path $venvPythonw) { $venvPythonw } elseif (Test-Path $preferredPythonw) { $preferredPythonw } elseif ($pythonw) { $pythonw.Source } else { 'python.exe' }
$desktopShortcut = Join-Path ([Environment]::GetFolderPath('Desktop')) '微信 AI.lnk'
$windowsPowerShell = Join-Path $env:WINDIR 'System32\WindowsPowerShell\v1.0\powershell.exe'
if (-not (Test-Path $windowsPowerShell)) {
  $pwshCommand = Get-Command pwsh.exe -ErrorAction SilentlyContinue
  $windowsPowerShell = if ($pwshCommand) { $pwshCommand.Source } else { 'powershell.exe' }
}
$command = '"' + $windowsPowerShell + '" -NoLogo -NoProfile -NonInteractive -ExecutionPolicy Bypass -WindowStyle Hidden -File "' + $bootstrap + '"'
$vbsCommand = $command.Replace('"', '""')
$desktopCommand = '"' + $desktopExe + '" "' + $desktopScript + '"'
$desktopVbsCommand = $desktopCommand.Replace('"', '""')
$vbsWorkingDirectory = $PSScriptRoot.Replace('"', '""')
$content = 'Set shell = CreateObject("WScript.Shell")' + "`r`n" +
  'shell.CurrentDirectory = "' + $vbsWorkingDirectory + '"' + "`r`n" +
  'shell.Run "' + $vbsCommand + '", 0, False'
$desktopContent = 'Set shell = CreateObject("WScript.Shell")' + "`r`n" +
  'shell.CurrentDirectory = "' + $vbsWorkingDirectory + '"' + "`r`n" +
  'shell.Run "' + $vbsCommand + '", 0, False' + "`r`n" +
  'shell.Run "' + $desktopVbsCommand + '", 0, False'
$wscript = Join-Path $env:WINDIR 'System32\wscript.exe'
if (-not (Test-Path $wscript)) {
  $wscriptCommand = Get-Command wscript.exe -ErrorAction SilentlyContinue
  $wscript = if ($wscriptCommand) { $wscriptCommand.Source } else { 'wscript.exe' }
}
if ($DryRun) {
  Write-Output "dry-run: set $runKey\$valueName -> $launcher"
  Write-Output "dry-run: create desktop bootstrap launcher -> $desktopLauncher"
  Write-Output "dry-run: create desktop shortcut -> $desktopShortcut"
  return
}
Set-Content -Path $launcher -Value $content -Encoding ascii
Set-Content -Path $desktopLauncher -Value $desktopContent -Encoding ascii
New-ItemProperty -Path $runKey -Name $valueName -Value ('wscript.exe "' + $launcher + '"') -PropertyType String -Force | Out-Null
$shell = New-Object -ComObject WScript.Shell
$shortcut = $shell.CreateShortcut($desktopShortcut)
$shortcut.TargetPath = $wscript
$shortcut.Arguments = '"' + $desktopLauncher + '"'
$shortcut.WorkingDirectory = $PSScriptRoot
$shortcut.Description = '微信 AI 桌面会话工作台'
$shortcut.Save()
Write-Output "startup registry entry created: $valueName"
Write-Output "desktop shortcut created: $desktopShortcut"
