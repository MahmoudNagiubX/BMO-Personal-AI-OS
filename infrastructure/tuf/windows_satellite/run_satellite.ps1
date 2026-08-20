[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$RepositoryRoot,
    [Parameter(Mandatory = $true)]
    [string]$ConfigPath
)

$ErrorActionPreference = 'Stop'
$repository = (Resolve-Path -LiteralPath $RepositoryRoot).Path
$configFile = (Resolve-Path -LiteralPath $ConfigPath).Path
$config = Get-Content -LiteralPath $configFile -Raw | ConvertFrom-Json

if ($null -eq $config.endpoint -or $null -eq $config.allowlist_path) {
    throw 'Satellite config must define endpoint and allowlist_path.'
}

$allowlist = (Resolve-Path -LiteralPath ([string]$config.allowlist_path)).Path
$python = Join-Path $repository '.venv\Scripts\python.exe'
$entrypoint = Join-Path $repository 'scripts\phase_09\run_windows_satellite.py'
if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
    throw 'The repository virtual-environment Python is missing.'
}
if (-not (Test-Path -LiteralPath $entrypoint -PathType Leaf)) {
    throw 'The reviewed Phase 9 entrypoint is missing.'
}

$env:BMO_SATELLITE_ENDPOINT = [string]$config.endpoint
$env:BMO_SATELLITE_ALLOWLIST_PATH = $allowlist
if ($null -ne $config.state_root) {
    $env:BMO_SATELLITE_STATE_ROOT = [string]$config.state_root
}

& $python $entrypoint
exit $LASTEXITCODE
