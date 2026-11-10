param([ValidateSet('prepare','start','status','plan','summarize','pause','clear-pause')][string]$Action = 'status')
$ErrorActionPreference = 'Stop'
$nightRoot = Split-Path -Parent $PSScriptRoot
Push-Location -LiteralPath $nightRoot
try {
    & (Join-Path $nightRoot '.venv/Scripts/python.exe') (Join-Path $PSScriptRoot 'overnight8.py') $Action
    if ($LASTEXITCODE -ne 0) { throw "Overnight command failed: $Action" }
} finally { Pop-Location }
