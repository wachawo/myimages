# Build the Windows artifact: the same frozen bundle the Linux packages carry,
# shipped as a zip.
#
# A zip rather than an installer. myImages keeps everything it persists under
# %USERPROFILE%\.myimages and writes nothing else, so unpacking it is a complete
# installation and deleting the folder is a complete removal. An installer would
# add a code-signing problem without solving one.
#
# Usage:  pwsh -File packaging/build_windows.ps1 [version]

param([string]$Version = "")

$ErrorActionPreference = "Stop"
$Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path

if (-not $Version) {
    # The version lives in one place; read it rather than repeating it here.
    $initPath = Join-Path $Root "myimages\__init__.py"
    $match = Select-String -Path $initPath -Pattern '^__version__ = "(.*)"$'
    if (-not $match) { throw "Could not read __version__ from $initPath" }
    $Version = $match.Matches[0].Groups[1].Value
}

$Stage = Join-Path ([System.IO.Path]::GetTempPath()) ("myimages-" + [System.Guid]::NewGuid().ToString("N"))
$DistDir = Join-Path $Stage "dist"
$WorkDir = Join-Path $Stage "build"
New-Item -ItemType Directory -Path $Stage -Force | Out-Null

try {
    Write-Host "==> Freezing the application"
    # The spec makes the executable windowed on Windows, so no console sits
    # behind the interface.
    & python -m PyInstaller --clean --noconfirm `
        --distpath $DistDir --workpath $WorkDir `
        (Join-Path $Root "packaging\myimages.spec")
    if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed with $LASTEXITCODE" }

    $bundle = Join-Path $DistDir "myimages"
    $exe = Join-Path $bundle "myimages.exe"
    if (-not (Test-Path $exe)) { throw "The build produced no myimages.exe" }

    Write-Host "==> Smoke test"
    # The one check worth making here: the frozen executable starts, finds its
    # own runtime and reports the version we think we built.
    $reported = & $exe --version
    Write-Host "    $reported"
    if ($reported -notmatch [regex]::Escape($Version)) {
        throw "The bundle reports '$reported', expected version $Version"
    }

    $archive = Join-Path $Root ("myImages-" + $Version + "-windows-x64.zip")
    if (Test-Path $archive) { Remove-Item $archive }
    Write-Host "==> Packing $archive"
    # Compress the directory itself, so unpacking gives one myimages\ folder
    # rather than scattering several hundred files into wherever the user is.
    Compress-Archive -Path $bundle -DestinationPath $archive -CompressionLevel Optimal
    Write-Host "Built $archive"
}
finally {
    Remove-Item -Recurse -Force $Stage -ErrorAction SilentlyContinue
}
