[CmdletBinding()]
param(
    [string]$RuntimeRoot = (Join-Path $env:LOCALAPPDATA 'BMO\Ollama\v0.32.5'),
    [string]$EvidenceRoot = (Join-Path $env:TEMP 'bmo-phase-04'),
    [int]$GracefulTimeoutSeconds = 10,
    [int]$PortReleaseTimeoutSeconds = 15
)

$ErrorActionPreference = 'Stop'

function Get-Phase4Binary {
    param([string]$Root)
    $candidates = @(Get-ChildItem -LiteralPath $Root -Filter 'ollama.exe' -File -Recurse | Where-Object {
            -not ($_.Attributes -band [IO.FileAttributes]::ReparsePoint)
        })
    if ($candidates.Count -ne 1) {
        throw 'The dedicated Phase 4 runtime must contain exactly one ollama.exe.'
    }
    return (Resolve-Path -LiteralPath $candidates[0].FullName).Path
}

function Get-ProcessExecutablePath {
    param([int]$ProcessId)
    $processInfo = Get-CimInstance Win32_Process -Filter "ProcessId = $ProcessId"
    if ($null -eq $processInfo -or [string]::IsNullOrWhiteSpace($processInfo.ExecutablePath)) {
        throw 'The dedicated process executable path could not be verified.'
    }
    return (Resolve-Path -LiteralPath $processInfo.ExecutablePath).Path
}

$pidPath = Join-Path $EvidenceRoot 'phase_04_ollama.pid'
$connections = @(Get-NetTCPConnection -LocalPort 11434 -ErrorAction SilentlyContinue)
if (-not (Test-Path -LiteralPath $pidPath -PathType Leaf)) {
    if ($connections.Count -gt 0) {
        throw 'Port 11434 is occupied but no Phase 4 PID record exists.'
    }
    Write-Output 'No dedicated Phase 4 Ollama process is running.'
    exit 0
}

$pidText = (Get-Content -LiteralPath $pidPath -Raw).Trim()
$phase4Pid = 0
if (-not [int]::TryParse($pidText, [ref]$phase4Pid) -or $phase4Pid -le 0) {
    throw 'The Phase 4 PID record is invalid.'
}
$expectedBinary = Get-Phase4Binary -Root $RuntimeRoot
$process = Get-Process -Id $phase4Pid -ErrorAction SilentlyContinue
if ($process) {
    $actualBinary = Get-ProcessExecutablePath -ProcessId $phase4Pid
    if (-not [StringComparer]::OrdinalIgnoreCase.Equals($actualBinary, $expectedBinary)) {
        throw 'The recorded PID does not belong to the dedicated Phase 4 Ollama binary.'
    }
    Stop-Process -Id $phase4Pid -ErrorAction Stop
    if (-not $process.WaitForExit($GracefulTimeoutSeconds * 1000)) {
        $stillRunning = Get-Process -Id $phase4Pid -ErrorAction SilentlyContinue
        if ($stillRunning) {
            Stop-Process -Id $phase4Pid -Force -ErrorAction Stop
            $stillRunning.WaitForExit(5000)
        }
    }
}

$deadline = (Get-Date).AddSeconds($PortReleaseTimeoutSeconds)
while ((Get-Date) -lt $deadline) {
    $connections = @(Get-NetTCPConnection -LocalPort 11434 -ErrorAction SilentlyContinue)
    if ($connections.Count -eq 0) {
        Remove-Item -LiteralPath $pidPath -Force
        Write-Output 'Phase 4 Ollama stopped and port 11434 released.'
        exit 0
    }
    Start-Sleep -Milliseconds 500
}
throw 'Port 11434 was not released by the dedicated Phase 4 Ollama process.'
