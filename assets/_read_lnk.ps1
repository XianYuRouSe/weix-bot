param([string]$Lnk = "$env:USERPROFILE\Desktop\微信回复机器人.lnk")
$ws = New-Object -ComObject WScript.Shell
$sc = $ws.CreateShortcut($Lnk)
"Target : " + $sc.TargetPath
"Args   : " + $sc.Arguments
"WorkDir: " + $sc.WorkingDirectory
"Icon   : " + $sc.IconLocation
