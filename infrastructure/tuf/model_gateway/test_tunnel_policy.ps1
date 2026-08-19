[CmdletBinding()]
param(
    [string]$KeyPath = (Join-Path $env:USERPROFILE '.ssh\venom_model_tunnel_ed25519'),
    [string]$RemoteHost = '192.162.1.21',
    [string]$RemoteUser = 'bmo-tunnel',
    [int]$LocalForwardPort = 41145,
    [int]$DynamicForwardPort = 41146,
    [int]$AlternateRemotePort = 41147
)

$ErrorActionPreference = 'Stop'
$sshPath = Join-Path $env:WINDIR 'System32\OpenSSH\ssh.exe'
$resolvedKey = (Resolve-Path -LiteralPath $KeyPath).Path
$processes = [System.Collections.Generic.List[System.Diagnostics.Process]]::new()
$temporary = [System.Collections.Generic.List[string]]::new()

function Start-TestSsh {
    param([string[]]$Arguments)
    $stdout = [System.IO.Path]::GetTempFileName()
    $stderr = [System.IO.Path]::GetTempFileName()
    $temporary.Add($stdout)
    $temporary.Add($stderr)
    $process = Start-Process -FilePath $sshPath -ArgumentList $Arguments -WindowStyle Hidden `
        -RedirectStandardOutput $stdout -RedirectStandardError $stderr -PassThru
    $processes.Add($process)
    return $process
}

function Stop-TestSsh {
    param([System.Diagnostics.Process]$Process)
    if (-not $Process.HasExited) {
        Stop-Process -Id $Process.Id -Force
        $Process.WaitForExit(5000) | Out-Null
    }
}

function Get-BaseArguments {
    return @(
        '-N', '-T', '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=5',
        '-o', 'ForwardAgent=no', '-o', 'ForwardX11=no',
        '-i', "`"$resolvedKey`""
    )
}

function Read-TcpBanner {
    param([int]$Port)
    $client = [System.Net.Sockets.TcpClient]::new()
    try {
        if (-not $client.ConnectAsync('127.0.0.1', $Port).Wait(3000)) { return '' }
        $stream = $client.GetStream()
        $stream.ReadTimeout = 3000
        $buffer = [byte[]]::new(128)
        try { $count = $stream.Read($buffer, 0, $buffer.Length) } catch { return '' }
        return [System.Text.Encoding]::ASCII.GetString($buffer, 0, $count)
    } finally {
        $client.Dispose()
    }
}

function Test-DynamicDenied {
    param([int]$Port)
    $client = [System.Net.Sockets.TcpClient]::new()
    try {
        if (-not $client.ConnectAsync('127.0.0.1', $Port).Wait(3000)) { return $true }
        $stream = $client.GetStream()
        $stream.ReadTimeout = 3000
        $stream.Write([byte[]](5, 1, 0), 0, 3)
        $greeting = [byte[]]::new(2)
        try { $read = $stream.Read($greeting, 0, 2) } catch { return $true }
        if ($read -ne 2 -or $greeting[0] -ne 5 -or $greeting[1] -ne 0) { return $true }
        $request = [byte[]](5, 1, 0, 1, 127, 0, 0, 1, 0, 22)
        $stream.Write($request, 0, $request.Length)
        $reply = [byte[]]::new(10)
        try { $read = $stream.Read($reply, 0, $reply.Length) } catch { return $true }
        return $read -lt 2 -or $reply[1] -ne 0
    } finally {
        $client.Dispose()
    }
}

try {
    foreach ($port in ($LocalForwardPort, $DynamicForwardPort)) {
        if (Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue) {
            throw "Local test port $port is already in use."
        }
    }

    $base = Get-BaseArguments
    $local = Start-TestSsh -Arguments ($base + @(
        '-L', "127.0.0.1:${LocalForwardPort}:127.0.0.1:22", "$RemoteUser@$RemoteHost"
    ))
    Start-Sleep -Seconds 1
    $localBanner = if ($local.HasExited) { '' } else { Read-TcpBanner -Port $LocalForwardPort }
    Stop-TestSsh -Process $local
    if ($localBanner.StartsWith('SSH-')) { throw 'Dedicated key allowed local TCP forwarding.' }

    $dynamic = Start-TestSsh -Arguments ($base + @(
        '-D', "127.0.0.1:$DynamicForwardPort", "$RemoteUser@$RemoteHost"
    ))
    Start-Sleep -Seconds 1
    $dynamicDenied = $dynamic.HasExited -or (Test-DynamicDenied -Port $DynamicForwardPort)
    Stop-TestSsh -Process $dynamic
    if (-not $dynamicDenied) { throw 'Dedicated key allowed dynamic TCP forwarding.' }

    $alternate = Start-TestSsh -Arguments ($base + @(
        '-o', 'ExitOnForwardFailure=yes',
        '-R', "127.0.0.1:${AlternateRemotePort}:127.0.0.1:11434",
        "$RemoteUser@$RemoteHost"
    ))
    if (-not $alternate.WaitForExit(8000)) {
        Stop-TestSsh -Process $alternate
        throw 'Dedicated key allowed an alternate remote listener.'
    }
    if ($alternate.ExitCode -eq 0) { throw 'Alternate remote-listen test unexpectedly succeeded.' }

    Write-Output 'local_forwarding_denied=true'
    Write-Output 'dynamic_forwarding_denied=true'
    Write-Output 'alternate_remote_listen_denied=true'
} finally {
    foreach ($process in $processes) { Stop-TestSsh -Process $process }
    foreach ($path in $temporary) { Remove-Item -LiteralPath $path -Force -ErrorAction SilentlyContinue }
}
