[CmdletBinding()]
param(
    [string]$RuntimeRoot = (Join-Path $env:USERPROFILE 'BMO\phase-08-5-runtime\cuda-b10502'),
    [string]$ModelPath = (Join-Path $env:USERPROFILE 'BMO\phase-08-5-models\Qwen3.5-9B-ultra-uncensored-heretic-v2-Q4_K_M.gguf'),
    [string]$StateRoot = (Join-Path $env:LOCALAPPDATA 'BMO\Phase08-5'),
    [int]$WaitSeconds = 180
)

$ErrorActionPreference = 'Stop'
$manifestPath = Join-Path $PSScriptRoot '..\model_manifest.json'
$manifest = Get-Content -LiteralPath $manifestPath -Raw | ConvertFrom-Json
$profile = $manifest.advanced_llama_cpp
if ($null -eq $profile -or $profile.build -ne 'b10502-0adcc3bb5' -or
    $profile.endpoint -ne '127.0.0.1:11435' -or $profile.n_gpu_layers -ne 20 -or
    $profile.context_tokens -ne 4096 -or $profile.kv_cache_type -ne 'q8_0' -or
    $profile.parallel -ne 1 -or $profile.flash_attention -ne $true -or
    $profile.vision -ne $false -or $profile.sleep_idle_seconds -ne 12) {
    throw 'The advanced llama.cpp manifest does not declare the measured admission profile.'
}
$principal = New-Object Security.Principal.WindowsPrincipal([Security.Principal.WindowsIdentity]::GetCurrent())
if ($principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    throw 'Do not run the advanced llama.cpp launcher as Administrator.'
}
$serverPath = Join-Path $RuntimeRoot 'llama-server.exe'
if (-not (Test-Path -LiteralPath $serverPath -PathType Leaf)) { throw 'Pinned llama-server.exe is missing.' }
if (-not (Test-Path -LiteralPath $ModelPath -PathType Leaf)) { throw 'Pinned advanced GGUF is missing.' }
$serverHash = (Get-FileHash -LiteralPath $serverPath -Algorithm SHA256).Hash.ToLowerInvariant()
if ($serverHash -ne $profile.server_executable_sha256) { throw 'llama-server.exe SHA-256 does not match the manifest.' }
$modelHash = (Get-FileHash -LiteralPath $ModelPath -Algorithm SHA256).Hash.ToLowerInvariant()
if ($modelHash -ne $profile.gguf_sha256) { throw 'The advanced GGUF SHA-256 does not match the manifest.' }
$listeners = @(Get-NetTCPConnection -LocalPort 11435 -State Listen -ErrorAction SilentlyContinue)
if ($listeners.Count -gt 0) { throw 'Port 11435 is already occupied.' }
$existing = @(Get-Process -Name llama-server -ErrorAction SilentlyContinue)
if ($existing.Count -gt 0) { throw 'An existing llama-server process must be handled before launch.' }
New-Item -ItemType Directory -Path $StateRoot -Force | Out-Null
$stdout = Join-Path $StateRoot 'llama-server.stdout.log'
$stderr = Join-Path $StateRoot 'llama-server.stderr.log'
$pidPath = Join-Path $StateRoot 'llama-server.pid'
$statePath = Join-Path $StateRoot 'llama-server.state.json'
Remove-Item -LiteralPath $stdout, $stderr, $pidPath, $statePath -Force -ErrorAction SilentlyContinue
$arguments = @(
    '-m', $ModelPath, '--host', '127.0.0.1', '--port', '11435',
    '-c', '4096', '-ngl', '20', '--parallel', '1',
    '--cache-type-k', 'q8_0', '--cache-type-v', 'q8_0', '--flash-attn', 'on',
    '--no-mmproj', '--no-webui', '--offline', '--props', '--sleep-idle-seconds', '12'
)
$process = Start-Process -FilePath $serverPath -ArgumentList $arguments -WorkingDirectory $RuntimeRoot `
    -WindowStyle Hidden -RedirectStandardOutput $stdout -RedirectStandardError $stderr -PassThru
[IO.File]::WriteAllText($pidPath, [string]$process.Id, [Text.UTF8Encoding]::new($false))
try {
    $deadline = (Get-Date).AddSeconds($WaitSeconds)
    $props = $null
    while ((Get-Date) -lt $deadline) {
        if ($process.HasExited) { throw 'llama-server exited before readiness.' }
        try {
            $health = Invoke-WebRequest -UseBasicParsing -Uri 'http://127.0.0.1:11435/health' -TimeoutSec 2
            if ($health.StatusCode -eq 200) {
                $props = Invoke-RestMethod -Uri 'http://127.0.0.1:11435/props' -TimeoutSec 5
                if ($props.build_info -eq $profile.build -and $props.model_path -eq $ModelPath) { break }
            }
        } catch { }
        Start-Sleep -Milliseconds 500
    }
    if ($null -eq $props -or $props.build_info -ne $profile.build -or $props.model_path -ne $ModelPath) {
        throw 'llama-server did not expose the exact pinned identity at readiness.'
    }
    $listeners = @(Get-NetTCPConnection -LocalPort 11435 -State Listen -ErrorAction SilentlyContinue)
    if (@($listeners | Where-Object { $_.LocalAddress -notin @('127.0.0.1', '::1') }).Count -gt 0) {
        throw 'llama-server has a non-loopback listener.'
    }
    $state = [ordered]@{
        pid = $process.Id
        build = $profile.build
        server_executable_sha256 = $serverHash
        gguf_filename = [IO.Path]::GetFileName($ModelPath)
        gguf_sha256 = $modelHash
        endpoint = '127.0.0.1:11435'
        arguments = $arguments
        n_safe_gpu_layers = 20
        gpu_split = '20/33'
        host_split = '13/33'
        context_tokens = 4096
        kv_cache_type = 'q8_0'
        flash_attention = $true
        parallel = 1
        vision = $false
        sleep_idle_seconds = 12
        loopback_only = $true
    }
    $state | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $statePath -Encoding utf8
    Write-Output 'PHASE_08_5_LLAMA_CPP_READY'
} catch {
    if (-not $process.HasExited) { Stop-Process -Id $process.Id -Force -ErrorAction SilentlyContinue }
    Remove-Item -LiteralPath $pidPath -Force -ErrorAction SilentlyContinue
    throw
}
