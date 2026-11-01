param([string]$LnkPath, [string]$Target, [string]$ArgLine, [string]$WorkDir, [string]$Icon, [string]$Desc)
$ErrorActionPreference = 'Stop'
$ws = New-Object -ComObject WScript.Shell
$sc = $ws.CreateShortcut($LnkPath)
$sc.TargetPath = $Target
$sc.Arguments = $ArgLine
$sc.WorkingDirectory = $WorkDir
$sc.IconLocation = $Icon
$sc.Description = $Desc
$sc.Save()
Write-Output ("saved: " + $LnkPath)
