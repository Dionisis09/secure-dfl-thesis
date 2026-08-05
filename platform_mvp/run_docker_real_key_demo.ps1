param(
    [string]$ProjectName = "secure_dfl_real_key_demo",
    [ValidateSet("none", "masking", "pairwise_masking")]
    [string]$SecurityMode = "pairwise_masking",
    [switch]$StopAfter
)

$ErrorActionPreference = "Stop"
if (Get-Variable -Name PSNativeCommandUseErrorActionPreference -Scope Global -ErrorAction SilentlyContinue) {
    $Global:PSNativeCommandUseErrorActionPreference = $false
}

function Invoke-Checked {
    param(
        [Parameter(Mandatory = $true)]
        [string[]]$Command
    )
    Write-Host ("`n> " + ($Command -join " "))
    & $Command[0] @($Command[1..($Command.Count - 1)])
    if ($LASTEXITCODE -ne 0) {
        throw "Command failed with exit code ${LASTEXITCODE}: $($Command -join ' ')"
    }
}

function Invoke-LoggedCommandLine {
    param(
        [Parameter(Mandatory = $true)]
        [string]$CommandLine,
        [Parameter(Mandatory = $true)]
        [string]$LogPath
    )
    Write-Host ("`n> " + $CommandLine)
    cmd.exe /d /c "$CommandLine 2>&1" | Tee-Object -FilePath $LogPath
    if ($LASTEXITCODE -ne 0) {
        throw "Command failed with exit code ${LASTEXITCODE}: $CommandLine"
    }
}

function Wait-HttpOk {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Url,
        [int]$TimeoutSeconds = 90
    )
    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    while ((Get-Date) -lt $deadline) {
        try {
            $response = Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec 3
            if ($response.StatusCode -eq 200) {
                return
            }
        } catch {
            Start-Sleep -Milliseconds 500
        }
    }
    throw "Timed out waiting for $Url"
}

$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$EvidenceDir = Join-Path $Root "results\docker_real_key_demo_latest"
$ResolvedRoot = (Resolve-Path $Root).Path
$ResultsRoot = Join-Path $ResolvedRoot "results"

if (Test-Path $EvidenceDir) {
    $resolvedEvidence = (Resolve-Path $EvidenceDir).Path
    if (-not $resolvedEvidence.StartsWith($ResultsRoot, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "Refusing to remove unexpected evidence path: $resolvedEvidence"
    }
    Remove-Item -LiteralPath $resolvedEvidence -Recurse -Force
}
New-Item -ItemType Directory -Force -Path $EvidenceDir | Out-Null

Push-Location $Root
try {
    $env:DFL_DOCKER_SECURITY_MODE = $SecurityMode

    Write-Host "Cleaning previous Docker demo resources..."
    & docker-compose -f docker-compose.real-keys.yml down -v --remove-orphans | Out-Null
    & docker-compose -p $ProjectName -f docker-compose.real-keys.yml down -v --remove-orphans | Out-Null

    Invoke-Checked @("docker-compose", "-p", $ProjectName, "-f", "docker-compose.real-keys.yml", "build")
    Invoke-Checked @("docker-compose", "-p", $ProjectName, "-f", "docker-compose.real-keys.yml", "up", "-d", "node0", "node1", "node2", "dashboard")

    Wait-HttpOk "http://localhost:9100/health"
    Wait-HttpOk "http://localhost:9101/health"
    Wait-HttpOk "http://localhost:9102/health"
    Wait-HttpOk "http://localhost:9200?token=docker-dashboard-token"

    Write-Host "`nRunning signed decentralized rounds..."
    Invoke-LoggedCommandLine `
        "docker-compose -p $ProjectName -f docker-compose.real-keys.yml run --rm --no-deps demo" `
        (Join-Path $EvidenceDir "demo_summary.json")

    Write-Host "`nVerifying signed audit logs..."
    Invoke-LoggedCommandLine `
        "docker-compose -p $ProjectName -f docker-compose.real-keys.yml run --rm --no-deps audit_verifier" `
        (Join-Path $EvidenceDir "audit_verifier_stdout.json")

    docker-compose -p $ProjectName -f docker-compose.real-keys.yml ps -a |
        Out-File -FilePath (Join-Path $EvidenceDir "docker_ps.txt") -Encoding utf8
    docker-compose -p $ProjectName -f docker-compose.real-keys.yml logs --no-color |
        Out-File -FilePath (Join-Path $EvidenceDir "docker_logs.txt") -Encoding utf8

    $reportContainer = (& docker create -v "${ProjectName}_real-reports:/reports" "secure_dfl_real_key_demo-audit_verifier:latest").Trim()
    try {
        Invoke-Checked @("docker", "cp", "${reportContainer}:/reports/docker_real_keys_audit_verification.json", (Join-Path $EvidenceDir "audit_verification.json"))
    }
    finally {
        & docker rm $reportContainer | Out-Null
    }
    foreach ($node in @("node0", "node1", "node2")) {
        Invoke-Checked @(
            "docker",
            "cp",
            "${ProjectName}-${node}-1:/data/node_audit.jsonl",
            (Join-Path $EvidenceDir "${node}_audit.jsonl")
        )
    }
    "status=PASS`nexport_method=docker cp`n" |
        Out-File -FilePath (Join-Path $EvidenceDir "evidence_copy.txt") -Encoding utf8

    $readme = @"
# Docker Real-Key Demo Evidence

Generated at: $(Get-Date -Format "yyyy-MM-dd HH:mm:ss")

Security mode: `$SecurityMode`

This folder contains the exported evidence from the Docker real-key Secure DFL demo.

Files:

- `demo_summary.json`: output from the orchestrated decentralized rounds.
- `audit_verifier_stdout.json`: stdout from audit verification.
- `audit_verification.json`: exported verification report from the Docker report volume.
- `node0_audit.jsonl`, `node1_audit.jsonl`, `node2_audit.jsonl`: signed per-node append-only audit logs.
- `docker_ps.txt`: Docker service status after the run.
- `docker_logs.txt`: combined Docker logs.

Dashboard:

`http://localhost:9200?token=docker-dashboard-token`

Interpretation:

PASS means the Docker stack generated real Ed25519 keys, started three independent nodes, completed signed decentralized rounds, verified aggregate correctness and verified signed hash-chained audit logs.
"@
    $readme | Out-File -FilePath (Join-Path $EvidenceDir "README_DEMO_EVIDENCE.md") -Encoding utf8

    Write-Host "`nDocker real-key demo completed successfully."
    Write-Host "Evidence folder: $EvidenceDir"
    Write-Host "Dashboard: http://localhost:9200?token=docker-dashboard-token"

    if ($StopAfter) {
        Invoke-Checked @("docker-compose", "-p", $ProjectName, "-f", "docker-compose.real-keys.yml", "down", "-v", "--remove-orphans")
    } else {
        Write-Host "Containers are still running for presentation. Stop them with:"
        Write-Host "docker-compose -p $ProjectName -f docker-compose.real-keys.yml down -v --remove-orphans"
    }
}
finally {
    Pop-Location
}
