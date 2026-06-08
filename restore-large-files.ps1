$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$ManifestPath = Join-Path $Root '_split_files_manifest.json'
if (!(Test-Path -LiteralPath $ManifestPath)) {
    Write-Host 'No split file manifest found. Nothing to restore.'
    exit 0
}
$Items = Get-Content -LiteralPath $ManifestPath -Raw -Encoding UTF8 | ConvertFrom-Json
foreach ($Item in $Items) {
    $Target = Join-Path $Root $Item.target
    New-Item -ItemType Directory -Force -Path (Split-Path $Target -Parent) | Out-Null
    if (Test-Path -LiteralPath $Target) { Remove-Item -LiteralPath $Target -Force }
    $Out = [System.IO.File]::Open($Target, [System.IO.FileMode]::CreateNew, [System.IO.FileAccess]::Write)
    try {
        foreach ($Part in $Item.parts) {
            $PartPath = Join-Path $Root $Part.path
            if (!(Test-Path -LiteralPath $PartPath)) { throw "Missing part: $($Part.path)" }
            $In = [System.IO.File]::OpenRead($PartPath)
            try { $In.CopyTo($Out) } finally { $In.Dispose() }
        }
    } finally { $Out.Dispose() }
    $Hash = (Get-FileHash -LiteralPath $Target -Algorithm SHA256).Hash.ToUpperInvariant()
    if ($Hash -ne [string]$Item.sha256) { throw "SHA256 mismatch: $($Item.target)" }
    Write-Host "Restored $($Item.target)"
}
Write-Host 'Large files restored successfully.'
