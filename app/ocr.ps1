# OCR a PNG file with the built-in Windows OCR engine and print recognised text.
# Used to verify that the currently open WeChat chat is the intended recipient
# BEFORE anything is typed or sent. No third-party dependency, no network.
param(
    [Parameter(Mandatory = $true)][string]$ImagePath,
    [string]$Language = "zh-Hans-CN",
    [switch]$Lines
)

$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Runtime.WindowsRuntime

$null = [Windows.Media.Ocr.OcrEngine, Windows.Foundation, ContentType = WindowsRuntime]
$null = [Windows.Graphics.Imaging.BitmapDecoder, Windows.Foundation, ContentType = WindowsRuntime]
$null = [Windows.Storage.StorageFile, Windows.Foundation, ContentType = WindowsRuntime]
$null = [Windows.Globalization.Language, Windows.Foundation, ContentType = WindowsRuntime]

# The BitmapDecoder used by Windows OCR does not reliably read the 24-bit BMP
# this project writes, so convert to PNG first (in-process, cheap).
if ([System.IO.Path]::GetExtension($ImagePath) -ieq ".bmp") {
    Add-Type -AssemblyName System.Drawing
    $img = [System.Drawing.Image]::FromFile($ImagePath)
    $png = [System.IO.Path]::ChangeExtension($ImagePath, ".png")
    $img.Save($png, [System.Drawing.Imaging.ImageFormat]::Png)
    $img.Dispose()
    $ImagePath = $png
}

$asTaskGeneric = ([System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object {
    $_.Name -eq 'AsTask' -and $_.GetParameters().Count -eq 1 -and
    $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1'
})[0]

function Await($WinRtTask, $ResultType) {
    $asTask = $asTaskGeneric.MakeGenericMethod($ResultType)
    $netTask = $asTask.Invoke($null, @($WinRtTask))
    $netTask.Wait(-1) | Out-Null
    $netTask.Result
}

$file = Await ([Windows.Storage.StorageFile]::GetFileFromPathAsync($ImagePath)) ([Windows.Storage.StorageFile])
$stream = Await ($file.OpenAsync([Windows.Storage.FileAccessMode]::Read)) ([Windows.Storage.Streams.IRandomAccessStream])
$decoder = Await ([Windows.Graphics.Imaging.BitmapDecoder]::CreateAsync($stream)) ([Windows.Graphics.Imaging.BitmapDecoder])
$bitmap = Await ($decoder.GetSoftwareBitmapAsync()) ([Windows.Graphics.Imaging.SoftwareBitmap])

$lang = New-Object Windows.Globalization.Language $Language
$engine = [Windows.Media.Ocr.OcrEngine]::TryCreateFromLanguage($lang)
if ($null -eq $engine) {
    Write-Error "OCR engine unavailable for $Language"
    exit 2
}

$result = Await ($engine.RecognizeAsync($bitmap)) ([Windows.Media.Ocr.OcrResult])
if ($Lines) {
    foreach ($line in $result.Lines) {
        $words = @($line.Words)
        if ($words.Count -eq 0) { continue }
        $first = $words[0].BoundingRect
        $last = $words[$words.Count - 1].BoundingRect
        $x = [int][double]$first.X
        $y = [int][double]$first.Y
        $right = [double]$last.X + [double]$last.Width
        $w = [int]($right - [double]$first.X)
        $h = [int][double]$first.Height
        $t = ($words | ForEach-Object { $_.Text }) -join ''
        Write-Output ("{0}`t{1}`t{2}`t{3}`t{4}" -f $t, $x, $y, $w, $h)
    }
} else {
    Write-Output $result.Text
}
