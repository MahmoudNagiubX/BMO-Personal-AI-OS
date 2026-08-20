[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidateSet('Start', 'Stop', 'Restart', 'Status', 'Remove')]
    [string]$Action
)

$ErrorActionPreference = 'Stop'
$taskName = 'BMO Phase 09 Windows Satellite'
$task = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue

if ($Action -eq 'Remove') {
    if ($null -ne $task) {
        Stop-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
        Unregister-ScheduledTask -TaskName $taskName -Confirm:$false
    }
    Write-Output 'PHASE_09_SATELLITE_TASK_REMOVED credential_preserved=true'
    exit 0
}
if ($null -eq $task) {
    throw 'The Phase 9 satellite task is not installed.'
}

switch ($Action) {
    'Start' { Start-ScheduledTask -TaskName $taskName }
    'Stop' { Stop-ScheduledTask -TaskName $taskName }
    'Restart' {
        Stop-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
        Start-ScheduledTask -TaskName $taskName
    }
    'Status' { }
}

Start-Sleep -Milliseconds 250
$current = Get-ScheduledTask -TaskName $taskName
$info = Get-ScheduledTaskInfo -TaskName $taskName
Write-Output ('PHASE_09_SATELLITE_TASK_STATUS state={0} last_result={1}' -f $current.State, $info.LastTaskResult)
