$runKey = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Run'
$valueName = 'WeChat AI Reply Daemon'
$value = (Get-ItemProperty -Path $runKey -Name $valueName -ErrorAction SilentlyContinue).$valueName
[pscustomobject]@{ Name = $valueName; Command = $value; Exists = [bool]$value } | Format-List
