param(
    [string]$CompilerRoot = "",
    [switch]$SkipTests
)
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path $PSScriptRoot -Parent
Set-Location -LiteralPath $projectRoot
$python = Join-Path $projectRoot '.venv/Scripts/python.exe'
if (!(Test-Path -LiteralPath $python)) { throw 'Run scripts/bootstrap.ps1 first.' }
$env:PYTHONPATH = Join-Path $projectRoot 'core'
$env:TMP = Join-Path $projectRoot 'build/tmp'
$env:TEMP = $env:TMP
New-Item -ItemType Directory -Force -Path $env:TMP | Out-Null
if (!$SkipTests -and (Test-Path -LiteralPath "tests")) {
    & $python -m pytest
    if ($LASTEXITCODE -ne 0) { throw 'Tests failed; package not generated.' }
}
$cmake = Join-Path $projectRoot '.venv/Lib/site-packages/cmake/data/bin/cmake.exe'
$ninja = Join-Path $projectRoot '.venv/Scripts/ninja.exe'
$configure = @('--fresh', '-S', '.', '-B', 'build/native', '-DCMAKE_BUILD_TYPE=Release', '-DSAVIOR_DEVELOPMENT_CORE=OFF')
if ($CompilerRoot) {
    $bin = Join-Path $CompilerRoot 'bin'
    $env:PATH = $bin + ';' + $env:PATH
    $cc = if (Test-Path -LiteralPath "$bin/clang.exe") { "$bin/clang.exe" } else { "$bin/gcc.exe" }
    $cxx = if (Test-Path -LiteralPath "$bin/clang++.exe") { "$bin/clang++.exe" } else { "$bin/g++.exe" }
    $configure += @('-G', 'Ninja', "-DCMAKE_MAKE_PROGRAM=$ninja", "-DCMAKE_C_COMPILER=$cc", "-DCMAKE_CXX_COMPILER=$cxx")
}
& $cmake @configure
if ($LASTEXITCODE -ne 0) { throw 'CMake configure failed.' }
& $cmake --build build/native --parallel 4
if ($LASTEXITCODE -ne 0) { throw 'C++ build failed.' }
& $python -m PyInstaller --noconfirm --clean --onedir --console --name savior-core --paths core --distpath dist/PCL-Savior --workpath build/pyinstaller scripts/core_entry.py
if ($LASTEXITCODE -ne 0) { throw 'Python core packaging failed.' }
$releaseRoot = Join-Path $projectRoot 'dist/PCL-Savior'
$app = Get-ChildItem -LiteralPath 'build/native' -Filter 'PCL Savior.exe' -Recurse | Select-Object -First 1
if (!$app) { throw 'Native executable not found.' }
Copy-Item -LiteralPath $app.FullName -Destination $releaseRoot -Force
Copy-Item -LiteralPath (Join-Path $app.DirectoryName 'assets') -Destination $releaseRoot -Recurse -Force
Copy-Item -LiteralPath 'README.md','THIRD_PARTY_NOTICES.md' -Destination $releaseRoot -Force
& $python scripts/collect_licenses.py
if ($LASTEXITCODE -ne 0) { throw 'License collection failed.' }
$archive = Join-Path $projectRoot 'dist/PCL-Savior-1.0.0-beta.1-windows-x64.zip'
& $python scripts/prepare_release.py
if ($LASTEXITCODE -ne 0) { throw "Public package preparation failed." }
Get-FileHash -LiteralPath $archive -Algorithm SHA256
