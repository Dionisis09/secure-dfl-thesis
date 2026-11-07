$ErrorActionPreference = 'Stop'
$simRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $simRoot
$simPython = Join-Path $simRoot '.venv\Scripts\python.exe'
& $simPython scripts\simulator50.py calibrate --pack simulator50_pack_20261107 --cache data\simulator50-cache --topologies ring
if ($LASTEXITCODE -ne 0) { throw 'Benchmark stopped; committed checkpoints were retained.' }
& $simPython scripts\simulator50.py plan --pack simulator50_pack_20261107
if ($LASTEXITCODE -ne 0) { throw 'Plan was not admitted.' }
