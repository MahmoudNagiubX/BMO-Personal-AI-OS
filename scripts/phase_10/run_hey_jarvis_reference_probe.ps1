#!/usr/bin/env pwsh
[CmdletBinding()]
param([string]$InputDevice)

$ErrorActionPreference = "Stop"
$repo = (Resolve-Path (Join-Path $PSScriptRoot "..\..\")).Path
Push-Location $repo
try {
    if ([string]::IsNullOrWhiteSpace($InputDevice)) {
        uv run python scripts/phase_10/run_hey_jarvis_reference_probe.py
    } else {
        uv run python scripts/phase_10/run_hey_jarvis_reference_probe.py --input-device $InputDevice
    }
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
} finally {
    Pop-Location
}
