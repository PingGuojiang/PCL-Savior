param([string]$Python = 'py')
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path $PSScriptRoot -Parent
Set-Location -LiteralPath $projectRoot
if (!(Test-Path -LiteralPath '.venv/Scripts/python.exe')) {
    & $Python -3.13 -m venv .venv
    if ($LASTEXITCODE -ne 0) { throw 'Python 3.13 environment creation failed.' }
}
$env:TMP = Join-Path $projectRoot 'build/tmp'
$env:TEMP = $env:TMP
New-Item -ItemType Directory -Force -Path $env:TMP | Out-Null
& '.venv/Scripts/python.exe' -m pip install -r requirements-dev.txt
if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed.' }
if (!(Test-Path -LiteralPath 'third_party/EUI-NEO/include/eui_neo.h')) {
    git clone https://github.com/sudoevolve/EUI-NEO.git third_party/EUI-NEO
    if ($LASTEXITCODE -ne 0) { throw 'EUI-NEO download failed.' }
}
git -C third_party/EUI-NEO checkout 1647709068e36834ab26da5a97ef4ad98aa34c9d
if ($LASTEXITCODE -ne 0) { throw 'EUI-NEO pin verification failed.' }
