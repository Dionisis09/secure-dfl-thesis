param([ValidateSet('prepare','preflight','calibrate','plan','status','run','summarize','pause','clear-pause')][string]$Action = 'status')
$ErrorActionPreference = 'Stop'
$laptopRoot = Split-Path -Parent $PSScriptRoot
$laptopPython = Join-Path $laptopRoot '.venv/Scripts/python.exe'
Push-Location -LiteralPath $laptopRoot
try {
    & $laptopPython (Join-Path $PSScriptRoot 'laptop24.py') $Action
    if ($LASTEXITCODE -ne 0) { throw "Laptop command failed: $Action" }
} finally { Pop-Location }
