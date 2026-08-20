[CmdletBinding()]
param(
    [ValidateSet('Install', 'Remove')]
    [string]$Action,
    [string]$KeyPath = (Join-Path $env:USERPROFILE '.ssh\venom_model_tunnel_ed25519')
)

$ErrorActionPreference = 'Stop'
$taskName = 'BMO Phase 5B Model Gateway Tunnel'
if ($Action -eq 'Remove') {
    Unregister-ScheduledTask -TaskName $taskName -Confirm:$false -ErrorAction SilentlyContinue
    Write-Output 'PHASE_05B_TUNNEL_TASK_REMOVED'
    exit 0
}
$config = Get-Content -LiteralPath (Join-Path $PSScriptRoot 'tunnel_config.json') -Raw |
    ConvertFrom-Json
if ($config.schema_version -ne 'phase-05b-reverse-ssh/v1' -or
    $config.remote_host -ne '192.162.1.21' -or
    $config.remote_user -ne 'bmo-tunnel' -or
    $config.remote_bind -ne '127.0.0.1:11434' -or
    $config.local_target -ne '127.0.0.1:11434' -or
    $config.advanced_remote_bind -ne '127.0.0.1:11435' -or
    $config.advanced_local_target -ne '127.0.0.1:11435') {
    throw 'The Scheduled Task tunnel configuration violates the locked loopback policy.'
}
$resolvedKey = (Resolve-Path -LiteralPath $KeyPath).Path
$sshPath = Join-Path $env:WINDIR 'System32\OpenSSH\ssh.exe'
if (-not (Test-Path -LiteralPath $sshPath -PathType Leaf)) {
    throw 'Windows OpenSSH client is unavailable at the expected system path.'
}
$arguments = @(
    '-N', '-T', '-o', 'BatchMode=yes', '-o', 'ExitOnForwardFailure=yes',
    '-o', 'ForwardAgent=no', '-o', 'ForwardX11=no',
    '-o', "ServerAliveInterval=$($config.server_alive_interval_seconds)",
    '-o', "ServerAliveCountMax=$($config.server_alive_count_max)",
    '-i', "`"$resolvedKey`"", '-R',
    "$($config.remote_bind):$($config.local_target)", '-R',
    "$($config.advanced_remote_bind):$($config.advanced_local_target)",
    "$($config.remote_user)@$($config.remote_host)"
) -join ' '
$taskAction = New-ScheduledTaskAction -Execute $sshPath -Argument $arguments
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
$settings = New-ScheduledTaskSettingsSet -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1) `
    -ExecutionTimeLimit (New-TimeSpan -Days 3650) -MultipleInstances IgnoreNew
$principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive -RunLevel Limited
Register-ScheduledTask -TaskName $taskName -Action $taskAction -Trigger $trigger `
    -Settings $settings -Principal $principal -Force | Out-Null
Write-Output 'PHASE_05B_TUNNEL_TASK_INSTALLED'
