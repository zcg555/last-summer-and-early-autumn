param([switch]$Extract)
$exePath = (Get-ChildItem -LiteralPath "$PSScriptRoot\input-v2.9" -Recurse -Filter '*.exe').FullName
$bytes = [IO.File]::ReadAllBytes($exePath)
function Read-BE32([int]$offset) {
    $v = [byte[]]$bytes[$offset..($offset+3)]
    [Array]::Reverse($v)
    [BitConverter]::ToUInt32($v,0)
}
$cookie = $bytes.Length - 88
$pkgLength = Read-BE32 ($cookie+8)
$tocOffset = Read-BE32 ($cookie+12)
$tocLength = Read-BE32 ($cookie+16)
$start = $bytes.Length - $pkgLength
$pos = $start + $tocOffset
$end = $pos + $tocLength
$outDir = Join-Path $PSScriptRoot 'recovered-v2.9'
if ($Extract) { [IO.Directory]::CreateDirectory($outDir) | Out-Null }
while ($pos -lt $end) {
    $entryLength = Read-BE32 $pos
    $offset = Read-BE32 ($pos+4)
    $length = Read-BE32 ($pos+8)
    $rawLength = Read-BE32 ($pos+12)
    $compressed = $bytes[$pos+16]
    $kind = [char]$bytes[$pos+17]
    $name = [Text.Encoding]::UTF8.GetString($bytes,$pos+18,$entryLength-18).TrimEnd([char]0)
    if ($Extract) {
        $target = [IO.Path]::GetFullPath((Join-Path $outDir $name))
        if (!$target.StartsWith($outDir + '\', [StringComparison]::OrdinalIgnoreCase)) { throw 'Unsafe archive path' }
        [IO.Directory]::CreateDirectory([IO.Path]::GetDirectoryName($target)) | Out-Null
        $data = [byte[]]::new($length)
        [Array]::Copy($bytes,$start+$offset,$data,0,$length)
        if ($compressed) {
            $inputStream = [IO.MemoryStream]::new($data)
            $z = [IO.Compression.ZLibStream]::new($inputStream,[IO.Compression.CompressionMode]::Decompress)
            $outputStream = [IO.MemoryStream]::new()
            $z.CopyTo($outputStream)
            $data = $outputStream.ToArray()
            $z.Dispose(); $inputStream.Dispose(); $outputStream.Dispose()
        }
        [IO.File]::WriteAllBytes($target,$data)
    }
    if ($kind -ne 'b' -and $kind -ne 'x') { "$kind`t$rawLength`t$name" }
    if ($name -match '\.py$|floor|reprice|\.json$|\.spec$') { "FILE`t$rawLength`t$name" }
    $pos += $entryLength
}
