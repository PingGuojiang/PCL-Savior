param([switch]$Rebuild, [string]$CompilerRoot = "", [switch]$SkipTests)
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path $PSScriptRoot -Parent
Set-Location -LiteralPath $projectRoot
$python = Join-Path $projectRoot '.venv/Scripts/python.exe'
$env:TMP = Join-Path $projectRoot 'build/tmp'
$env:TEMP = $env:TMP
New-Item -ItemType Directory -Force -Path $env:TMP | Out-Null
if ($Rebuild) {
    & (Join-Path $PSScriptRoot 'build.ps1') -CompilerRoot $CompilerRoot -SkipTests:$SkipTests
}
& $python (Join-Path $PSScriptRoot 'prepare_release.py')
if ($LASTEXITCODE -ne 0) { throw 'Payload preparation failed.' }
$work = Join-Path $projectRoot 'build/singlefile-input'
New-Item -ItemType Directory -Force -Path $work | Out-Null
$payload = Join-Path $work 'payload.zip'
Copy-Item -LiteralPath 'dist/PCL-Savior-1.0.0-beta.1-windows-x64.zip' -Destination $payload -Force
$checksum = Join-Path $work 'payload.sha256'
(Get-FileHash -LiteralPath $payload -Algorithm SHA256).Hash.ToLowerInvariant() | Set-Content -LiteralPath $checksum -Encoding ascii
$name = 'PCL-Savior-1.0.0-beta.1-windows-x64-single'
& $python -m PyInstaller --noconfirm --clean --onefile --windowed --noupx --name $name --icon assets/app.ico --add-data "$payload;." --add-data "$checksum;." --distpath dist --workpath build/pyinstaller-single scripts/singlefile_entry.py
if ($LASTEXITCODE -ne 0) { throw 'Single EXE packaging failed.' }
Get-FileHash -LiteralPath (Join-Path $projectRoot "dist/$name.exe") -Algorithm SHA256
