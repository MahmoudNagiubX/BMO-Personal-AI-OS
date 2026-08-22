[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$RepositoryRoot,
    [Parameter(Mandatory = $true)]
    [string]$ConfigPath
)

$ErrorActionPreference = 'Stop'
$taskName = 'BMO Phase 09 Windows Satellite'
$repository = (Resolve-Path -LiteralPath $RepositoryRoot).Path
$config = (Resolve-Path -LiteralPath $ConfigPath).Path
$runner = Join-Path $repository 'infrastructure\tuf\windows_satellite\run_satellite.ps1'
if (-not (Test-Path -LiteralPath $runner -PathType Leaf)) {
    throw 'The reviewed Phase 9 runner is missing.'
}

$powerShell = (Get-Command powershell.exe -ErrorAction Stop).Source
$arguments = @(
    '-NoProfile'
    '-NonInteractive'
    '-ExecutionPolicy'
    'RemoteSigned'
    '-File'
    ('"{0}"' -f $runner)
    '-RepositoryRoot'
    ('"{0}"' -f $repository)
    '-ConfigPath'
    ('"{0}"' -f $config)
) -join ' '

$action = New-ScheduledTaskAction -Execute $powerShell -Argument $arguments
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
$settings = New-ScheduledTaskSettingsSet -RestartCount 3 `
    -RestartInterval (New-TimeSpan -Minutes 1) `
    -ExecutionTimeLimit (New-TimeSpan -Days 7) `
    -MultipleInstances IgnoreNew
$principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME `
    -LogonType Interactive -RunLevel Limited

Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger `
    -Settings $settings -Principal $principal -Description 'BMO Phase 9 outbound-only Windows satellite' `
    -Force | Out-Null
Write-Output 'PHASE_09_SATELLITE_TASK_INSTALL_PASS run_level=limited trigger=at_logon'
