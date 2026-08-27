# Full System Automated Acceptance Runner for PowerShell on Windows
[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Definition
$repoRoot = Split-Path -Parent $scriptDir

Write-Host "======================================================================" -ForegroundColor Cyan
Write-Host " BMO / JARVIS Personal AI OS - Full System Acceptance (PowerShell)" -ForegroundColor Cyan
Write-Host "======================================================================" -ForegroundColor Cyan

Set-Location $repoRoot

& uv run python "$scriptDir\run_full_system_acceptance.py"
if ($LASTEXITCODE -ne 0) {
    Write-Error "Full system automated acceptance failed with exit code $LASTEXITCODE"
    exit $LASTEXITCODE
}

Write-Host ""
Write-Host "Full system automated acceptance completed successfully." -ForegroundColor Green
