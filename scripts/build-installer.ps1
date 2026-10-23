param(
    [string]$IsccPath = "",
    [switch]$Rebuild,
    [string]$CompilerRoot = "",
    [switch]$SkipTests
)
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path $PSScriptRoot -Parent
Set-Location -LiteralPath $projectRoot
$env:TMP = Join-Path $projectRoot 'build/tmp'
$env:TEMP = $env:TMP
New-Item -ItemType Directory -Force -Path $env:TMP | Out-Null
if ($Rebuild) {
    & (Join-Path $PSScriptRoot 'build.ps1') -CompilerRoot $CompilerRoot -SkipTests:$SkipTests
}
$releaseRoot = Join-Path $projectRoot 'dist/PCL-Savior'
foreach ($required in @('PCL Savior.exe','savior-core/savior-core.exe','savior-core/_internal/python313.dll','assets/app.png')) {
    if (!(Test-Path -LiteralPath (Join-Path $releaseRoot $required))) { throw "Incomplete portable payload: $required" }
}
$python = Join-Path $projectRoot '.venv/Scripts/python.exe'
& $python (Join-Path $PSScriptRoot 'collect_licenses.py')
if ($LASTEXITCODE -ne 0) { throw 'License collection failed.' }
if (!$IsccPath) {
    $candidates = @((Join-Path $projectRoot '.tools/InnoSetup-6.7.3/ISCC.exe'),
                    "${env:ProgramFiles(x86)}/Inno Setup 6/ISCC.exe", "$env:ProgramFiles/Inno Setup 6/ISCC.exe")
    $IsccPath = $candidates | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
}
if (!$IsccPath -or !(Test-Path -LiteralPath $IsccPath)) { throw 'Install Inno Setup 6.7.3 or pass -IsccPath.' }
& $python (Join-Path $PSScriptRoot 'prepare_release.py')
if ($LASTEXITCODE -ne 0) { throw 'Public package preparation failed.' }
$payload = Join-Path $projectRoot 'build/public-release'
& $IsccPath '/Qp' ("/DPayloadDir=$payload") (Join-Path $projectRoot 'installer/PCLSavior.iss')
if ($LASTEXITCODE -ne 0) { throw 'Installer compilation failed.' }
$installer = Join-Path $projectRoot 'dist/PCL-Savior-1.0.0-beta.1-windows-x64-setup.exe'
Get-FileHash -LiteralPath $installer -Algorithm SHA256
