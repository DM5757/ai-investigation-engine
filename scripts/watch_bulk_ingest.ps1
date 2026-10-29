# Resumable overnight bulk ingest watchdog (Windows).
# Restarts `bulk_ingest.py` from checkpoint if the process exits before done.
# Usage (leave a terminal open overnight):
#   powershell -ExecutionPolicy Bypass -File scripts/watch_bulk_ingest.ps1

$ErrorActionPreference = "Continue"
$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $Root

$Checkpoint = Join-Path $Root "data\checkpoints\bulk_ingest.json"
$LogDir = Join-Path $Root "data\logs"
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
$Stamp = Get-Date -Format "yyyyMMdd_HHmmss"
$OutLog = Join-Path $LogDir "watch_bulk_$Stamp.out.log"
$ErrLog = Join-Path $LogDir "watch_bulk_$Stamp.err.log"

function Test-BulkDone {
    if (-not (Test-Path $Checkpoint)) { return $false }
    try {
        $ck = Get-Content $Checkpoint -Raw | ConvertFrom-Json
        return [bool]$ck.done
    } catch {
        return $false
    }
}

Write-Host "watch_bulk_ingest root=$Root"
Write-Host "logs: $OutLog"

while (-not (Test-BulkDone)) {
    Write-Host "$(Get-Date -Format o) starting bulk_ingest (resume via checkpoint if present)"
    $env:PYTHONUNBUFFERED = "1"
    $p = Start-Process -FilePath "uv" `
        -ArgumentList @("run", "python", "-u", "scripts/bulk_ingest.py", "--max-docs", "55000", "--checkpoint-every", "50", "--batch-size", "16") `
        -WorkingDirectory $Root `
        -RedirectStandardOutput $OutLog `
        -RedirectStandardError $ErrLog `
        -PassThru -WindowStyle Hidden
    Wait-Process -Id $p.Id
    Write-Host "$(Get-Date -Format o) bulk exited code=$($p.ExitCode)"
    if (Test-BulkDone) { break }
    Write-Host "not done; sleeping 15s then resume"
    Start-Sleep -Seconds 15
}

Write-Host "$(Get-Date -Format o) bulk checkpoint reports done=true"
& uv run python scripts/verify_counts.py
& uv run python scripts/compute_bm25_stats.py
& uv run python scripts/crc32_collision_analysis.py
Write-Host "post-bulk verification scripts finished"
