param([string]$Version = "0.1.0")

# 打包发布：只复制可发布的文件 → 扫描个人痕迹 → 打 zip
# 用法：powershell -File 打包发布.ps1 -Version 0.1.0
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$stage = Join-Path $root "_dist\weix-bot"
$dist = Join-Path $root "dist"

Write-Host "== 1/4 清理旧产物 =="
if (Test-Path $stage) { Remove-Item $stage -Recurse -Force }
New-Item -ItemType Directory -Force -Path $stage | Out-Null
New-Item -ItemType Directory -Force -Path $dist | Out-Null

Write-Host "== 2/4 复制白名单文件 =="
$include = @(
  "app\*.py", "app\ocr.ps1",
  "assets\*.png", "assets\*.ico",
  "assets\make_icon.ps1", "assets\make_shortcut.ps1",
  "config.example\*.json",
  "docs\*.md",
  "LICENSE", "README.md", ".gitignore", "VERSION",
  "首次配置.bat", "启动机器人.bat", "停止机器人.bat", "打开控制面板.bat"
)
$count = 0
foreach ($pat in $include) {
  Get-ChildItem -Path (Join-Path $root $pat) -File -ErrorAction SilentlyContinue | ForEach-Object {
    $rel = $_.FullName.Substring($root.Length).TrimStart('\')
    $dst = Join-Path $stage $rel
    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $dst) | Out-Null
    Copy-Item $_.FullName $dst -Force
    $count++
  }
}
Write-Host ("   复制了 {0} 个文件" -f $count)

Write-Host "== 3/4 扫描个人痕迹 =="
$bad = @()
# 通用规则：任何像 API key 的东西
$patterns = @('sk-[0-9a-fA-F]{20,}')
# 本机专属规则放 packaging.private.txt（不进 Git、不进包），没有就只做通用检查
$privFile = Join-Path $root "packaging.private.txt"
if (Test-Path $privFile) {
  $privLines = Get-Content $privFile -Encoding UTF8 | Where-Object { $_.Trim() -ne "" -and -not $_.Trim().StartsWith("#") }
  foreach ($line in $privLines) { $patterns += [regex]::Escape($line.Trim()) }
  Write-Host ("   已加载本机私密规则 {0} 条" -f $privLines.Count)
} else {
  Write-Host "   没有 packaging.private.txt，只做通用检查（建议自建，写上你的 wxid / 本机路径）"
}
# 这些是运行数据文件名，一旦出现在包里就说明漏了
$dataFiles = @('all_keys.json', 'profiles.json', 'bot.json', 'state.json',
               'bot.log', 'evolve.log', 'bot.lock', 'panel.lock', '.env')
foreach ($f in Get-ChildItem $stage -Recurse -File) {
  if ($f.Extension -in @('.db', '.log', '.env', '.pyc', '.jks')) {
    $bad += ("{0}: 不该出现的运行数据（{1}）" -f $f.FullName, $f.Extension)
    continue
  }
  if (($dataFiles -contains $f.Name) -and ($f.FullName -notmatch '\\config\.example\\')) {
    $bad += ("{0}: 运行数据文件被打进包了" -f $f.FullName)
    continue
  }
  $text = ""
  try { $text = [System.IO.File]::ReadAllText($f.FullName) } catch { }
  foreach ($p in $patterns) {
    if ($text -match $p) { $bad += ("{0}: 命中 {1}" -f $f.FullName, $p) }
  }
}
if ($bad.Count -gt 0) {
  Write-Host "   发现可疑内容，已中止：" -ForegroundColor Red
  $bad | ForEach-Object { Write-Host ("   [X] " + $_) -ForegroundColor Red }
  throw "打包取消"
}
Write-Host "   干净：没有 wxid / API key / 聊天库 / 本机路径"

Write-Host "== 4/4 生成清单并压缩 =="
Set-Content -Path (Join-Path $stage "VERSION") -Value $Version -Encoding UTF8
$lines = @("weix-bot $Version", "")
foreach ($f in Get-ChildItem $stage -Recurse -File | Sort-Object FullName) {
  $rel = $f.FullName.Substring($stage.Length).TrimStart('\')
  $hash = (Get-FileHash $f.FullName -Algorithm SHA256).Hash.ToLower()
  $lines += ("{0}  {1}" -f $hash.Substring(0, 16), $rel)
}
$lines += ""
$lines += "运行数据（config/ logs/ cache/ .env）不包含在此包内，首次运行由 首次配置.bat 生成。"
Set-Content -Path (Join-Path $stage "MANIFEST.txt") -Value ($lines -join "`r`n") -Encoding UTF8

$zip = Join-Path $dist ("weix-bot-{0}.zip" -f $Version)
if (Test-Path $zip) { Remove-Item $zip -Force }
Compress-Archive -Path $stage -DestinationPath $zip -CompressionLevel Optimal
$size = [math]::Round((Get-Item $zip).Length / 1KB, 1)
Write-Host ("   已生成 {0}（{1} KB）" -f $zip, $size) -ForegroundColor Green

Get-ChildItem $stage -Recurse -File | ForEach-Object {
  Write-Host ("   + " + $_.FullName.Substring($stage.Length).TrimStart('\'))
}
