[CmdletBinding()]
param(
    [string]$RuntimeRoot = (Join-Path $env:USERPROFILE 'BMO\phase-08-5-runtime\cuda-b10502'),
    [string]$StateRoot = (Join-Path $env:LOCALAPPDATA 'BMO\Phase08-5'),
    [int]$TimeoutSeconds = 15
)

$ErrorActionPreference = 'Stop'
$pidPath = Join-Path $StateRoot 'llama-server.pid'
if (-not (Test-Path -LiteralPath $pidPath -PathType Leaf)) {
    if (@(Get-NetTCPConnection -LocalPort 11435 -State Listen -ErrorAction SilentlyContinue).Count -gt 0) {
        throw 'Port 11435 is occupied without an owned llama.cpp PID record.'
    }
    Write-Output 'PHASE_08_5_LLAMA_CPP_STOPPED'
    exit 0
}
$pidValue = (Get-Content -LiteralPath $pidPath -Raw).Trim()
$processId = 0
if (-not [int]::TryParse($pidValue, [ref]$processId) -or $processId -le 0) { throw 'llama.cpp PID record is invalid.' }
$process = Get-Process -Id $processId -ErrorAction SilentlyContinue
if ($null -ne $process) {
    $info = Get-CimInstance Win32_Process -Filter "ProcessId = $processId"
    $expected = (Resolve-Path -LiteralPath (Join-Path $RuntimeRoot 'llama-server.exe')).Path
    if ($null -eq $info -or $info.ExecutablePath -ne $expected) { throw 'PID record is not the pinned llama-server.' }
    Stop-Process -Id $processId -ErrorAction Stop
}
$deadline = (Get-Date).AddSeconds($TimeoutSeconds)
while ((Get-Date) -lt $deadline) {
    if ($null -eq (Get-Process -Id $processId -ErrorAction SilentlyContinue) -and
        @(Get-NetTCPConnection -LocalPort 11435 -State Listen -ErrorAction SilentlyContinue).Count -eq 0) {
        Remove-Item -LiteralPath $pidPath -Force
        Write-Output 'PHASE_08_5_LLAMA_CPP_STOPPED'
        exit 0
    }
    Start-Sleep -Milliseconds 250
}
throw 'Pinned llama.cpp process or listener did not stop within the bound.'
