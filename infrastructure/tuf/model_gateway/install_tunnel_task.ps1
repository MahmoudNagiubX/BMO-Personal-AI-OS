[CmdletBinding()]
param(
    [ValidateSet('Install', 'Remove')]
    [string]$Action,
    [string]$TunnelScript = ''
)

$ErrorActionPreference = 'Stop'
if ([string]::IsNullOrWhiteSpace($TunnelScript)) {
    $TunnelScript = Join-Path $PSScriptRoot 'manage_tunnel.ps1'
}
$taskName = 'BMO Phase 5B Model Gateway Tunnel'
if ($Action -eq 'Remove') {
    Unregister-ScheduledTask -TaskName $taskName -Confirm:$false -ErrorAction SilentlyContinue
    Write-Output 'PHASE_05B_TUNNEL_TASK_REMOVED'
    exit 0
}
$resolved = (Resolve-Path -LiteralPath $TunnelScript).Path
$taskAction = New-ScheduledTaskAction -Execute 'powershell.exe' -Argument (
    "-NoProfile -NonInteractive -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$resolved`" -Action Run"
)
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
$settings = New-ScheduledTaskSettingsSet -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1) `
    -ExecutionTimeLimit (New-TimeSpan -Days 3650) -MultipleInstances IgnoreNew
$principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive -RunLevel Limited
Register-ScheduledTask -TaskName $taskName -Action $taskAction -Trigger $trigger `
    -Settings $settings -Principal $principal -Force | Out-Null
Write-Output 'PHASE_05B_TUNNEL_TASK_INSTALLED'
