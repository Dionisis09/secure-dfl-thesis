$ErrorActionPreference = 'Stop'
$simRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $simRoot
$simPython = Join-Path $simRoot '.venv\Scripts\python.exe'
& $simPython scripts\simulator50.py run --pack simulator50_pack_20261107 --cache data\simulator50-cache
if ($LASTEXITCODE -ne 0) { throw 'Simulator stopped; inspect state and job logs. No automatic retry.' }
