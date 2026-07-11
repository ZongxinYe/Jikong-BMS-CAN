param(
    [switch]$SkipArchive,
    [switch]$SkipBuild
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$SpecPath = Join-Path $ProjectRoot "packaging\bms_can_monitor.spec"
$ReleaseDirectory = Join-Path $ProjectRoot "dist\BMS-CAN-Monitor"
$ArchivePath = Join-Path $ProjectRoot "dist\BMS-CAN-Monitor-windows-x64.zip"

Push-Location $ProjectRoot
try {
    if (-not $SkipBuild) {
        python -c "import struct, sys; sys.exit(0 if struct.calcsize('P') * 8 == 64 else 1)"
        if ($LASTEXITCODE -ne 0) {
            throw "The Windows release must be built with 64-bit Python."
        }

        python -m PyInstaller --noconfirm --clean $SpecPath
        if ($LASTEXITCODE -ne 0) {
            throw "PyInstaller build failed."
        }
    }
    elseif (-not (Test-Path $ReleaseDirectory)) {
        throw "Release directory does not exist: $ReleaseDirectory"
    }

    $DocumentationDirectory = Join-Path $ReleaseDirectory "Documentation"
    New-Item -ItemType Directory -Force $DocumentationDirectory | Out-Null
    Copy-Item -LiteralPath (Join-Path $ProjectRoot "README.md") -Destination $DocumentationDirectory -Force
    Copy-Item -LiteralPath (Join-Path $ProjectRoot "docs\phase5-control-safety.md") -Destination $DocumentationDirectory -Force
    Copy-Item -LiteralPath (Join-Path $ProjectRoot "docs\phase6-windows-release.md") -Destination $DocumentationDirectory -Force
    Copy-Item -LiteralPath (Join-Path $ProjectRoot "docs\phase6-field-validation.md") -Destination $DocumentationDirectory -Force

    python -B tools\verify_windows_release.py $ReleaseDirectory
    if ($LASTEXITCODE -ne 0) {
        throw "Release resource verification failed."
    }
    python -B tools\write_release_manifest.py $ReleaseDirectory
    if ($LASTEXITCODE -ne 0) {
        throw "Release manifest generation failed."
    }

    if (-not $SkipArchive) {
        if (Test-Path $ArchivePath) {
            Remove-Item -LiteralPath $ArchivePath -Force
        }
        Compress-Archive -Path $ReleaseDirectory -DestinationPath $ArchivePath -CompressionLevel Optimal
        $ArchiveHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $ArchivePath).Hash
        Set-Content -LiteralPath ($ArchivePath + ".sha256") -Value ($ArchiveHash + "  " + (Split-Path -Leaf $ArchivePath)) -Encoding ascii
        Write-Host "Archive: $ArchivePath"
    }
    Write-Host "Release: $ReleaseDirectory"
}
finally {
    Pop-Location
}
