[CmdletBinding()]
param(
    [ValidateSet('Preflight', 'Start', 'Run', 'Verify', 'Status', 'Stop')]
    [string]$Action = 'Status',
    [string]$KeyPath = (Join-Path $env:USERPROFILE '.ssh\venom_model_tunnel_ed25519'),
    [string]$AdminKeyPath = (Join-Path $env:USERPROFILE '.ssh\venom_ed25519'),
    [string]$StateRoot = (Join-Path $env:LOCALAPPDATA 'BMO\Phase05B'),
    [int]$ReadyTimeoutSeconds = 20
)

$ErrorActionPreference = 'Stop'
$configPath = Join-Path $PSScriptRoot 'tunnel_config.json'
$config = Get-Content -LiteralPath $configPath -Raw | ConvertFrom-Json
$statePath = Join-Path $StateRoot 'tunnel-state.json'
$sshPath = Join-Path $env:WINDIR 'System32\OpenSSH\ssh.exe'

function Assert-Configuration {
    if ($config.schema_version -ne 'phase-05b-reverse-ssh/v1' -or
        $config.remote_host -ne '192.162.1.21' -or
        $config.remote_user -ne 'venom' -or
        $config.remote_bind -ne '127.0.0.1:11434' -or
        $config.local_target -ne '127.0.0.1:11434' -or
        $config.batch_mode -ne $true -or
        $config.exit_on_forward_failure -ne $true -or
        $config.agent_forwarding -ne $false -or
        $config.x11_forwarding -ne $false -or
        $config.pty -ne $false) {
        throw 'The Phase 5B tunnel configuration violates the locked loopback policy.'
    }
    if (-not (Test-Path -LiteralPath $sshPath -PathType Leaf)) {
        throw 'Windows OpenSSH client is unavailable at the expected system path.'
    }
}

function Get-TunnelArguments {
    return @(
        '-N', '-T',
        '-o', 'BatchMode=yes',
        '-o', 'ExitOnForwardFailure=yes',
        '-o', 'ForwardAgent=no',
        '-o', 'ForwardX11=no',
        '-o', "ServerAliveInterval=$($config.server_alive_interval_seconds)",
        '-o', "ServerAliveCountMax=$($config.server_alive_count_max)",
        '-i', (Resolve-Path -LiteralPath $KeyPath).Path,
        '-R', "$($config.remote_bind):$($config.local_target)",
        "$($config.remote_user)@$($config.remote_host)"
    )
}

function Get-RecordedProcess {
    if (-not (Test-Path -LiteralPath $statePath -PathType Leaf)) { return $null }
    $state = Get-Content -LiteralPath $statePath -Raw | ConvertFrom-Json
    $processId = 0
    if (-not [int]::TryParse([string]$state.pid, [ref]$processId) -or $processId -le 0) {
        throw 'The Phase 5B tunnel state file is invalid.'
    }
    $process = Get-CimInstance Win32_Process -Filter "ProcessId = $processId"
    if ($null -eq $process) { return $null }
    $expected = (Resolve-Path -LiteralPath $sshPath).Path
    if (-not [StringComparer]::OrdinalIgnoreCase.Equals($expected, $process.ExecutablePath)) {
        throw 'The recorded PID does not belong to Windows OpenSSH.'
    }
    $requiredFragments = @(
        'BatchMode=yes', 'ExitOnForwardFailure=yes', 'ForwardAgent=no', 'ForwardX11=no',
        '127.0.0.1:11434:127.0.0.1:11434', 'venom@192.162.1.21'
    )
    foreach ($fragment in $requiredFragments) {
        if ($process.CommandLine -notlike "*$fragment*") {
            throw 'The recorded OpenSSH process is not the reviewed Phase 5B tunnel.'
        }
    }
    return $process
}

function Assert-OllamaLoopback {
    $listeners = @(Get-NetTCPConnection -LocalPort 11434 -State Listen -ErrorAction SilentlyContinue)
    if ($listeners.Count -eq 0) { throw 'Ollama is not listening on the TUF.' }
    if (@($listeners | Where-Object { $_.LocalAddress -notin @('127.0.0.1', '::1') }).Count) {
        throw 'Ollama has a non-loopback listener; refusing to open the tunnel.'
    }
    $version = Invoke-RestMethod -Uri 'http://127.0.0.1:11434/api/version' -TimeoutSec 2
    if ($version.version -ne '0.32.5') { throw 'Ollama version does not match 0.32.5.' }
    $inventory = Invoke-RestMethod -Uri 'http://127.0.0.1:11434/api/tags' -TimeoutSec 3
    $expected = @{
        'qwen3.5:4b' = '2a654d98e6fba55d452b7043684e9b57a947e393bbffa62485a7aac05ee4eefd'
        'bge-m3:567m' = '7907646426070047a77226ac3e684fbbe8410524f7b4a74d02837e43f2146bab'
    }
    foreach ($entry in $expected.GetEnumerator()) {
        $model = @($inventory.models | Where-Object { $_.name -eq $entry.Key })
        if ($model.Count -ne 1 -or $model[0].digest -ne $entry.Value) {
            throw "Accepted model identity mismatch for $($entry.Key)."
        }
    }
    if (@($inventory.models | Where-Object { $_.name -match '^qwen3\.5:9b' }).Count -gt 0) {
        throw 'Qwen3.5 9B is deferred and must not be active in Phase 5B.'
    }
}

function Test-RemoteGateway {
    if (-not (Test-Path -LiteralPath $AdminKeyPath -PathType Leaf)) {
        throw 'The VENOM administrator key required for read-only verification is missing.'
    }
    $savedPreference = $ErrorActionPreference
    try {
        $ErrorActionPreference = 'Continue'
        & $sshPath -T -o BatchMode=yes -o ConnectTimeout=5 -i $AdminKeyPath `
            "venom@$($config.remote_host)" `
            'curl -fsS --max-time 2 http://127.0.0.1:11434/api/version >/dev/null' 2>$null
        return ($LASTEXITCODE -eq 0)
    } finally {
        $ErrorActionPreference = $savedPreference
    }
}

Assert-Configuration
if ($Action -in @('Preflight', 'Start', 'Run', 'Verify')) {
    if (-not (Test-Path -LiteralPath $KeyPath -PathType Leaf)) {
        throw 'The dedicated Phase 5B tunnel private key is missing.'
    }
    Assert-OllamaLoopback
}

switch ($Action) {
    'Preflight' {
        Write-Output 'PHASE_05B_TUNNEL_PREFLIGHT_PASS'
    }
    'Start' {
        $existing = Get-RecordedProcess
        if ($null -ne $existing) { Write-Output 'PHASE_05B_TUNNEL_ALREADY_RUNNING'; break }
        New-Item -ItemType Directory -Path $StateRoot -Force | Out-Null
        $process = Start-Process -FilePath $sshPath -ArgumentList (Get-TunnelArguments) `
            -WindowStyle Hidden -PassThru
        @{ pid = $process.Id; started_utc = (Get-Date).ToUniversalTime().ToString('o') } |
            ConvertTo-Json | Set-Content -LiteralPath $statePath -Encoding utf8
        $deadline = (Get-Date).AddSeconds($ReadyTimeoutSeconds)
        while ((Get-Date) -lt $deadline) {
            if ($process.HasExited) { throw 'The reverse SSH tunnel exited before readiness.' }
            if (Test-RemoteGateway) { Write-Output 'PHASE_05B_TUNNEL_READY'; break }
            Start-Sleep -Milliseconds 500
        }
        if (-not (Test-RemoteGateway)) { throw 'VENOM could not reach loopback Ollama.' }
    }
    'Run' {
        & $sshPath @(Get-TunnelArguments)
        exit $LASTEXITCODE
    }
    'Verify' {
        if ($null -eq (Get-RecordedProcess)) { throw 'The reviewed tunnel process is not running.' }
        if (-not (Test-RemoteGateway)) { throw 'The reverse tunnel is not healthy.' }
        Write-Output 'PHASE_05B_TUNNEL_VERIFY_PASS'
    }
    'Status' {
        if ($null -eq (Get-RecordedProcess)) { Write-Output 'PHASE_05B_TUNNEL_STOPPED' }
        else { Write-Output 'PHASE_05B_TUNNEL_RUNNING' }
    }
    'Stop' {
        $process = Get-RecordedProcess
        if ($null -ne $process) {
            Stop-Process -Id $process.ProcessId -ErrorAction Stop
            $deadline = (Get-Date).AddSeconds(10)
            while ((Get-Date) -lt $deadline -and (Get-Process -Id $process.ProcessId -ErrorAction SilentlyContinue)) {
                Start-Sleep -Milliseconds 200
            }
            if (Get-Process -Id $process.ProcessId -ErrorAction SilentlyContinue) {
                throw 'The reviewed tunnel process did not stop within the bound.'
            }
        }
        Remove-Item -LiteralPath $statePath -Force -ErrorAction SilentlyContinue
        Write-Output 'PHASE_05B_TUNNEL_STOPPED'
    }
}
