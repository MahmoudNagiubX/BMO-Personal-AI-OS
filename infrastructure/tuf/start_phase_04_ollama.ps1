[CmdletBinding()]
param(
    [string]$RuntimeRoot = (Join-Path $env:LOCALAPPDATA 'BMO\Ollama\v0.32.5'),
    [string]$ModelRoot = (Join-Path $env:LOCALAPPDATA 'BMO\Ollama\models'),
    [string]$EvidenceRoot = (Join-Path $env:TEMP 'bmo-phase-04'),
    [int]$WaitSeconds = 45
)

$ErrorActionPreference = 'Stop'

function Get-Phase4Binary {
    param([string]$Root)
    if (-not (Test-Path -LiteralPath $Root -PathType Container)) {
        throw 'The dedicated Phase 4 runtime root does not exist.'
    }
    $candidates = @(Get-ChildItem -LiteralPath $Root -Filter 'ollama.exe' -File -Recurse | Where-Object {
            -not ($_.Attributes -band [IO.FileAttributes]::ReparsePoint)
        })
    if ($candidates.Count -ne 1) {
        throw 'The dedicated Phase 4 runtime must contain exactly one ollama.exe.'
    }
    return (Resolve-Path -LiteralPath $candidates[0].FullName).Path
}

function Assert-LoopbackListener {
    param([int]$ExpectedPid)
    $listeners = @(Get-NetTCPConnection -LocalPort 11434 -State Listen -ErrorAction SilentlyContinue)
    if ($listeners.Count -eq 0) {
        return $false
    }
    foreach ($listener in $listeners) {
        if ($listener.LocalAddress -notin @('127.0.0.1', '::1')) {
            throw 'Ollama is listening on a non-loopback address.'
        }
        if ([int]$listener.OwningProcess -ne $ExpectedPid) {
            throw 'An unrelated process owns the Ollama listener.'
        }
    }
    return $true
}

function Update-CloudConfig {
    param([string]$EvidencePath)
    $configDirectory = Join-Path ([Environment]::GetFolderPath('UserProfile')) '.ollama'
    $configPath = Join-Path $configDirectory 'server.json'
    New-Item -ItemType Directory -Path $configDirectory -Force | Out-Null
    $backupPath = $null
    if (Test-Path -LiteralPath $configPath -PathType Leaf) {
        $backupPath = Join-Path $EvidencePath ('server.json.' + (Get-Date).ToUniversalTime().ToString('yyyyMMddTHHmmssZ') + '.bak')
        Copy-Item -LiteralPath $configPath -Destination $backupPath -Force
        $config = Get-Content -LiteralPath $configPath -Raw | ConvertFrom-Json
        if ($null -eq $config -or $config -isnot [pscustomobject]) {
            throw 'Existing Ollama server.json is not a JSON object.'
        }
    } else {
        $config = [pscustomobject]@{}
    }
    if ($null -eq $config.PSObject.Properties['disable_ollama_cloud']) {
        $config | Add-Member -NotePropertyName 'disable_ollama_cloud' -NotePropertyValue $true
    } else {
        $config.disable_ollama_cloud = $true
    }
    $json = $config | ConvertTo-Json -Depth 20
    [IO.File]::WriteAllText($configPath, $json + [Environment]::NewLine, [Text.UTF8Encoding]::new($false))
    return [pscustomobject]@{
        path_changed = $true
        backup_created = [bool]$backupPath
        disable_ollama_cloud = $true
    }
}

function Assert-ConservativeRuntimeProfile {
    param([object]$Profile)
    if ($null -eq $Profile -or $Profile.profile -ne 'conservative_cuda') {
        throw 'The model manifest does not declare the conservative CUDA profile.'
    }
    if ($Profile.flash_attention -ne $true) {
        throw 'The conservative CUDA profile must enable Flash Attention.'
    }
    if ($Profile.kv_cache_type -ne 'q8_0') {
        throw 'The conservative CUDA profile must use q8_0 KV cache.'
    }
    $gpuOverhead = 0L
    if (-not [long]::TryParse([string]$Profile.gpu_overhead_bytes, [ref]$gpuOverhead) -or
        $gpuOverhead -le 0 -or $gpuOverhead -gt 8589934592 -or $gpuOverhead -ne 536870912) {
        throw 'The conservative CUDA GPU overhead is invalid.'
    }
    if ($Profile.max_parallel_requests -ne 1) {
        throw 'The conservative CUDA profile must allow one parallel request.'
    }
    if ($Profile.max_loaded_models -ne 1) {
        throw 'The conservative CUDA profile must allow one loaded model.'
    }
    if ($Profile.keep_alive -ne '0') {
        throw 'The conservative CUDA profile must unload with zero keep-alive.'
    }
    if ($Profile.listener -ne '127.0.0.1:11434') {
        throw 'The Phase 4 listener must remain loopback-only.'
    }
    if ($Profile.cloud_disabled -ne $true) {
        throw 'The conservative CUDA profile must disable cloud access.'
    }
}

$phase4Identity = [Security.Principal.WindowsIdentity]::GetCurrent()
$phase4Principal = New-Object Security.Principal.WindowsPrincipal($phase4Identity)
if ($phase4Principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    throw 'Do not run the Phase 4 Ollama launcher as Administrator.'
}

$manifestPath = Join-Path $PSScriptRoot 'model_manifest.json'
$manifest = Get-Content -LiteralPath $manifestPath -Raw | ConvertFrom-Json
if ($manifest.ollama_version -ne '0.32.5' -or $manifest.runtime.version -ne '0.32.5') {
    throw 'The model manifest does not pin Ollama v0.32.5.'
}
Assert-ConservativeRuntimeProfile -Profile $manifest.runtime_profile
$expectedSha = [string]$manifest.runtime.executable_sha256
if ($expectedSha -notmatch '^[0-9a-fA-F]{64}$') {
    throw 'The model manifest does not contain the verified Ollama executable SHA-256.'
}

$binaryPath = Get-Phase4Binary -Root $RuntimeRoot
$actualSha = (Get-FileHash -LiteralPath $binaryPath -Algorithm SHA256).Hash.ToLowerInvariant()
$hashesMatch = [StringComparer]::OrdinalIgnoreCase.Equals($expectedSha, $actualSha)
if (-not $hashesMatch) {
    throw 'The dedicated Ollama executable SHA-256 does not match the manifest.'
}

$existingPort = @(Get-NetTCPConnection -LocalPort 11434 -State Listen -ErrorAction SilentlyContinue)
if ($existingPort.Count -gt 0) {
    throw 'Port 11434 is already occupied.'
}
$existingOllama = @(Get-Process -Name ollama -ErrorAction SilentlyContinue)
if ($existingOllama.Count -gt 0) {
    throw 'An existing Ollama process must be preserved and handled before Phase 4 launch.'
}
if (-not [string]::IsNullOrWhiteSpace($env:OLLAMA_API_KEY)) {
    throw 'OLLAMA_API_KEY is present; refusing to launch.'
}

New-Item -ItemType Directory -Path $ModelRoot -Force | Out-Null
New-Item -ItemType Directory -Path $EvidenceRoot -Force | Out-Null
$configEvidence = Update-CloudConfig -EvidencePath $EvidenceRoot
$env:OLLAMA_HOST = '127.0.0.1:11434'
$env:OLLAMA_MODELS = $ModelRoot
$env:OLLAMA_NO_CLOUD = '1'
$env:OLLAMA_FLASH_ATTENTION = '1'
$env:OLLAMA_KV_CACHE_TYPE = 'q8_0'
$env:OLLAMA_GPU_OVERHEAD = '536870912'
$env:OLLAMA_NUM_PARALLEL = '1'
$env:OLLAMA_MAX_LOADED_MODELS = '1'
$env:OLLAMA_KEEP_ALIVE = '0'
$env:OLLAMA_DEBUG = '1'
Remove-Item Env:CUDA_VISIBLE_DEVICES -ErrorAction SilentlyContinue
Remove-Item Env:OLLAMA_LLM_LIBRARY -ErrorAction SilentlyContinue
Remove-Item Env:OLLAMA_API_KEY -ErrorAction SilentlyContinue

$stdoutPath = Join-Path $EvidenceRoot 'ollama.stdout.log'
$stderrPath = Join-Path $EvidenceRoot 'ollama.stderr.log'
$pidPath = Join-Path $EvidenceRoot 'phase_04_ollama.pid'
$process = Start-Process -FilePath $binaryPath -ArgumentList @('serve') -WorkingDirectory $RuntimeRoot -WindowStyle Hidden -RedirectStandardOutput $stdoutPath -RedirectStandardError $stderrPath -PassThru
[IO.File]::WriteAllText($pidPath, [string]$process.Id, [Text.UTF8Encoding]::new($false))

try {
    $deadline = (Get-Date).AddSeconds($WaitSeconds)
    $version = $null
    while ((Get-Date) -lt $deadline) {
        if ($process.HasExited) {
            throw 'The dedicated Ollama process exited before the local API became ready.'
        }
        $listenerReady = Assert-LoopbackListener -ExpectedPid $process.Id
        if ($listenerReady) {
            try {
                $version = Invoke-RestMethod -Uri 'http://127.0.0.1:11434/api/version' -TimeoutSec 3
            } catch {
                $version = $null
            }
            if ($version -and $version.version -eq '0.32.5') {
                break
            }
        }
        Start-Sleep -Milliseconds 500
    }
    if (-not $version -or $version.version -ne '0.32.5') {
        throw 'The dedicated Ollama API did not become ready at version 0.32.5.'
    }
    Assert-LoopbackListener -ExpectedPid $process.Id | Out-Null
    $logText = ((Get-Content -LiteralPath $stdoutPath -ErrorAction SilentlyContinue) + (Get-Content -LiteralPath $stderrPath -ErrorAction SilentlyContinue)) -join "`n"
    $profileConfirmed = [ordered]@{
        flash_attention = [bool]($logText -match '(?i)OLLAMA_FLASH_ATTENTION:true')
        kv_cache_q8_0 = [bool]($logText -match '(?i)OLLAMA_KV_CACHE_TYPE:q8_0')
        gpu_overhead = [bool]($logText -match '(?i)OLLAMA_GPU_OVERHEAD:536870912')
        single_parallel = [bool]($logText -match '(?i)OLLAMA_NUM_PARALLEL:1')
        single_loaded_model = [bool]($logText -match '(?i)OLLAMA_MAX_LOADED_MODELS:1')
        zero_keep_alive = [bool]($logText -match '(?i)OLLAMA_KEEP_ALIVE:0s')
        cloud_disabled = [bool]($logText -match '(?i)OLLAMA_NO_CLOUD:true')
    }
    if (@($profileConfirmed.Values | Where-Object { -not $_ }).Count -gt 0) {
        throw 'The dedicated Ollama startup evidence did not confirm the conservative CUDA profile.'
    }
    [pscustomobject]@{
        pid = $process.Id
        version = $version.version
        ollama_host = '127.0.0.1:11434'
        ollama_no_cloud = $true
        api_key_inherited = $false
        server_config_disable_ollama_cloud = [bool]$configEvidence.disable_ollama_cloud
        server_log_cloud_disabled_observed = [bool]($logText -match '(?i)cloud.{0,20}disabled|disabled.{0,20}cloud')
        conservative_cuda_profile = $profileConfirmed
        loopback_only = $true
    } | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath (Join-Path $EvidenceRoot 'phase_04_launch.json') -Encoding utf8
    Write-Output 'Phase 4 Ollama is ready on loopback.'
} catch {
    if (-not $process.HasExited) {
        Stop-Process -Id $process.Id -ErrorAction SilentlyContinue
    }
    Remove-Item -LiteralPath $pidPath -Force -ErrorAction SilentlyContinue
    throw
}
