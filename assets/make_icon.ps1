param(
    [Parameter(Mandatory = $true)][string]$Dir
)
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Drawing

$S = 256
$bmp = New-Object System.Drawing.Bitmap $S, $S, ([System.Drawing.Imaging.PixelFormat]::Format32bppArgb)
$g = [System.Drawing.Graphics]::FromImage($bmp)
$g.SmoothingMode = [System.Drawing.Drawing2D.SmoothingMode]::AntiAlias
$g.Clear([System.Drawing.Color]::Transparent)

function RoundRect($g, $brush, $x, $y, $w, $h, $r) {
    $d = $r * 2
    $p = New-Object System.Drawing.Drawing2D.GraphicsPath
    $p.AddArc($x, $y, $d, $d, 180, 90)
    $p.AddArc($x + $w - $d, $y, $d, $d, 270, 90)
    $p.AddArc($x + $w - $d, $y + $h - $d, $d, $d, 0, 90)
    $p.AddArc($x, $y + $h - $d, $d, $d, 90, 90)
    $p.CloseFigure()
    $g.FillPath($brush, $p)
    $p.Dispose()
}

$bg = New-Object System.Drawing.SolidBrush ([System.Drawing.Color]::FromArgb(255, 26, 30, 38))
RoundRect $g $bg 6 6 244 244 54
$bg.Dispose()

$green = New-Object System.Drawing.SolidBrush ([System.Drawing.Color]::FromArgb(255, 46, 194, 126))
RoundRect $g $green 44 58 168 116 30
$tail = New-Object System.Drawing.Drawing2D.GraphicsPath
$tail.AddPolygon(@(
    (New-Object System.Drawing.Point 84, 168),
    (New-Object System.Drawing.Point 84, 208),
    (New-Object System.Drawing.Point 128, 168)
))
$g.FillPath($green, $tail)
$tail.Dispose()
$green.Dispose()

$white = New-Object System.Drawing.SolidBrush ([System.Drawing.Color]::White)
foreach ($cx in @(96, 128, 160)) { $g.FillEllipse($white, ($cx - 11), 105, 22, 22) }
$white.Dispose()
$g.Dispose()

$png = Join-Path $Dir 'weix.png'
$bmp.Save($png, [System.Drawing.Imaging.ImageFormat]::Png)
$bmp.Dispose()

$bytes = [System.IO.File]::ReadAllBytes($png)
$ms = New-Object System.IO.MemoryStream
$bw = New-Object System.IO.BinaryWriter($ms)
$bw.Write([UInt16]0)
$bw.Write([UInt16]1)
$bw.Write([UInt16]1)
$bw.Write([Byte]0)
$bw.Write([Byte]0)
$bw.Write([Byte]0)
$bw.Write([Byte]0)
$bw.Write([UInt16]1)
$bw.Write([UInt16]32)
$bw.Write([UInt32]$bytes.Length)
$bw.Write([UInt32]22)
$bw.Write($bytes, 0, $bytes.Length)
$bw.Flush()

$ico = Join-Path $Dir 'weix.ico'
[System.IO.File]::WriteAllBytes($ico, $ms.ToArray())
$bw.Dispose()
$ms.Dispose()

$check = New-Object System.Drawing.Icon $ico
Write-Output ("icon ok: {0} ({1}x{2})" -f $ico, $check.Width, $check.Height)
$check.Dispose()
