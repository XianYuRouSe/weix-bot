param([string]$Version = "0.1.1")

# 打成免装 Python 的 exe 包：一个 weix.exe + 少量资源
# 用法：powershell -File 打包exe.ps1 -Version 0.1.1
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$dist = Join-Path $root "out-exe\weix"
$zip = Join-Path $root ("dist\weix-bot-{0}-exe.zip" -f $Version)

Write-Host "== 1/4 构建 exe =="
$py = (Get-Command python -ErrorAction SilentlyContinue).Source
if (-not $py) { $py = "C:\Python314\python.exe" }
if (-not (Test-Path $py)) { throw "找不到 python.exe" }
Push-Location $root
cmd /c ('"{0}" -m PyInstaller --noconfirm --clean --console --name weix --paths app app\launcher.py --distpath out-exe --workpath build-exe --specpath build-exe >nul 2>&1' -f $py)
$code = $LASTEXITCODE
Pop-Location
if ($code -ne 0) { throw ("PyInstaller 失败（退出码 {0}）" -f $code) }
Write-Host "   构建完成"

Write-Host "== 2/4 补齐资源 =="
New-Item -ItemType Directory -Force -Path "$dist\app", "$dist\assets" | Out-Null
Copy-Item (Join-Path $root "app\ocr.ps1") "$dist\app\" -Force
Copy-Item (Join-Path $root "assets\weix.ico") "$dist\assets\" -Force
Copy-Item (Join-Path $root "assets\weix.png") "$dist\assets\" -Force
[System.IO.File]::WriteAllText("$dist\VERSION", $Version, (New-Object System.Text.UTF8Encoding($false)))

# 三个入口脚本（纯 ASCII，避免编码问题）
$bat = @{
  "启动机器人.bat" = "@echo off`r`nsetlocal`r`nset `"APP=%~dp0`"`r`ncd /d `"%APP%`"`r`nstart `"`" /min `"%APP%weix.exe`" bot`r`nexit /b 0`r`n"
  "打开控制面板.bat" = "@echo off`r`nsetlocal`r`nset `"APP=%~dp0`"`r`ncd /d `"%APP%`"`r`nstart `"`" `"%APP%weix.exe`" panel`r`nexit /b 0`r`n"
  "首次配置.bat" = "@echo off`r`nsetlocal`r`nchcp 65001 >nul`r`nset `"APP=%~dp0`"`r`ncd /d `"%APP%`"`r`n`"%APP%weix.exe`" setup %*`r`necho.`r`npause`r`nexit /b 0`r`n"
  "自检.bat" = "@echo off`r`nsetlocal`r`nchcp 65001 >nul`r`nset `"APP=%~dp0`"`r`ncd /d `"%APP%`"`r`n`"%APP%weix.exe`" selftest`r`necho.`r`npause`r`nexit /b 0`r`n"
}
foreach ($k in $bat.Keys) {
  [System.IO.File]::WriteAllText((Join-Path $dist $k), $bat[$k], [System.Text.Encoding]::GetEncoding(936))
}
Write-Host ("   资源补齐：{0}" -f (Get-ChildItem $dist -File | Measure-Object).Count)

Write-Host "== 3/4 扫描个人数据 =="
$bad = @()
$patterns = @('sk-[0-9a-fA-F]{20,}')
$privFile = Join-Path $root "packaging.private.txt"
if (Test-Path $privFile) {
  (Get-Content $privFile -Encoding UTF8) | Where-Object { $_.Trim() -ne "" -and -not $_.Trim().StartsWith("#") } |
    ForEach-Object { $patterns += [regex]::Escape($_.Trim()) }
}
$dataNames = @('all_keys.json', 'profiles.json', 'bot.json', 'state.json', '.env', 'bot.log', 'evolve.log')
foreach ($f in Get-ChildItem $dist -Recurse -File) {
  if ($dataNames -contains $f.Name) { $bad += ("{0}: 运行数据" -f $f.FullName); continue }
  if ($f.Extension -in @('.db', '.log', '.env')) { $bad += ("{0}: 运行数据" -f $f.FullName); continue }
  $text = ""
  try { $text = [System.IO.File]::ReadAllText($f.FullName) } catch { }
  foreach ($p in $patterns) { if ($text -match $p) { $bad += ("{0}: 命中 {1}" -f $f.FullName, $p) } }
}
if ($bad.Count -gt 0) {
  $bad | ForEach-Object { Write-Host ("   [X] " + $_) -ForegroundColor Red }
  throw "exe 打包中止"
}
Write-Host "   干净"

Write-Host "== 4/4 压缩 =="
if (Test-Path $zip) { Remove-Item $zip -Force }
Compress-Archive -Path $dist -DestinationPath $zip -CompressionLevel Optimal
Write-Host ("   已生成 {0}（{1} MB）" -f $zip, [math]::Round((Get-Item $zip).Length / 1MB, 1)) -ForegroundColor Green
