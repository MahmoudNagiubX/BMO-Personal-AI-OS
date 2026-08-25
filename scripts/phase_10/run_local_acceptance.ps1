<#
.SYNOPSIS
    Run the single combined local Phase 10 ASUS TUF acceptance session.

The Core bearer credential is requested once by the Python runner through a
local hidden prompt. It is never an argument, environment variable, log, or
evidence value. BMO_VOICE_SESSION_ID is an optional non-secret pre-created Core
session identifier; if absent the runner creates one through authenticated Core.
BMO_VOICE_CORE_URL may override the private VENOM origin.
#>
$ErrorActionPreference = "Stop"
$repo = (Resolve-Path (Join-Path $PSScriptRoot "../..")).Path
$voiceRoot = Join-Path $env:LOCALAPPDATA "BMO\VoiceModels"
$wakeVerifier = Join-Path $voiceRoot "faster-whisper-base.en"
$heyJarvisModel = Join-Path $repo ".venv\Lib\site-packages\openwakeword\resources\models\hey_jarvis_v0.1.onnx"
$heyJarvisSha256 = "94a13cfe60075b132f6a472e7e462e8123ee70861bc3fb58434a73712ee0d2cb"
$stt = Join-Path $voiceRoot "faster-whisper-medium"
$arabicRoot = Join-Path $voiceRoot "vits-piper-ar_JO-kareem-medium"
$englishRoot = Join-Path $voiceRoot "vits-piper-en_US-lessac-medium"
$ttsData = Join-Path $voiceRoot "espeak-ng-data"
$cudaRoot = Get-ChildItem (Join-Path $env:LOCALAPPDATA "BMO\llama.cpp") -Directory -Recurse |
    Where-Object {
        (Test-Path (Join-Path $_.FullName "cudart64_12.dll")) -and
        (Test-Path (Join-Path $_.FullName "cublas64_12.dll"))
    } |
    Select-Object -First 1
$ctranslate2Root = Join-Path $repo ".venv\Lib\site-packages\ctranslate2"
$sessionId = [Environment]::GetEnvironmentVariable("BMO_VOICE_SESSION_ID")
$inputDevice = [Environment]::GetEnvironmentVariable("BMO_VOICE_INPUT_DEVICE")
$outputDevice = [Environment]::GetEnvironmentVariable("BMO_VOICE_OUTPUT_DEVICE")
$resumeStageA = [Environment]::GetEnvironmentVariable("BMO_VOICE_RESUME_STAGE_A")
$configuredCoreUrl = [Environment]::GetEnvironmentVariable("BMO_VOICE_CORE_URL")
$coreUrl = $configuredCoreUrl
$tunnelProcess = $null
$exitCode = 1
foreach ($required in @($wakeVerifier, (Join-Path $wakeVerifier "model.bin"), $stt, (Join-Path $arabicRoot "ar_JO-kareem-medium.onnx"), (Join-Path $arabicRoot "tokens.txt"), (Join-Path $englishRoot "en_US-lessac-medium.onnx"), (Join-Path $englishRoot "tokens.txt"), $ttsData)) {
    if (-not (Test-Path -LiteralPath $required)) { throw "Required local voice artifact is missing: $required" }
}
if (-not (Test-Path -LiteralPath $heyJarvisModel)) { throw "Official Hey Jarvis model is missing from the pinned openWakeWord package" }
if ((Get-FileHash -Algorithm SHA256 -LiteralPath $heyJarvisModel).Hash.ToLowerInvariant() -ne $heyJarvisSha256) {
    throw "Official Hey Jarvis model checksum mismatch"
}
if ($null -eq $cudaRoot) { throw "No local CUDA runtime directory with cudart64_12.dll and cublas64_12.dll was found" }
if (-not (Test-Path -LiteralPath (Join-Path $ctranslate2Root "cudnn64_9.dll"))) {
    throw "Pinned CTranslate2 cuDNN runtime is missing: cudnn64_9.dll"
}
$commit = (& git -C $repo rev-parse HEAD).Trim()
if ($commit -notmatch '^[0-9a-f]{40}$') { throw "Unable to resolve the exact physical-tested commit" }
$output = Join-Path $repo "docs\phase_reports\evidence\PHASE_10_JARVIS_VOICE_CORE.json"
try {
    if ([string]::IsNullOrWhiteSpace($configuredCoreUrl)) {
        $coreUrl = "http://127.0.0.1:18000"
        $existing = Get-NetTCPConnection -LocalPort 18000 -State Listen -ErrorAction SilentlyContinue
        if ($null -ne $existing) {
            $probeOk = $false
            try {
                $probe = Invoke-RestMethod -Uri "http://127.0.0.1:18000/health/live" -TimeoutSec 2 -ErrorAction Stop
                if ($probe.status -eq "ok") { $probeOk = $true }
            } catch {
                $probeOk = $false
            }
            if (-not $probeOk) {
                throw "LOCAL_PORT_CONFLICT: Port 18000 is already in use by an unverified process or dead listener"
            }
        } else {
            $key = Join-Path $env:USERPROFILE ".ssh\venom_ed25519"
            if (-not (Test-Path -LiteralPath $key)) { throw "SSH_KEY_MISSING: Verified VENOM SSH key is missing" }

            $sshStderrFile = [System.IO.Path]::GetTempFileName()
            try {
                $tunnelProcess = Start-Process -FilePath ssh.exe -WindowStyle Hidden -PassThru -ArgumentList @(
                    "-N", "-L", "18000:127.0.0.1:8000",
                    "-o", "BatchMode=yes",
                    "-o", "ExitOnForwardFailure=yes",
                    "-o", "ConnectTimeout=10",
                    "-o", "LogLevel=ERROR",
                    "-i", $key,
                    "venom@192.162.1.25"
                ) -RedirectStandardError $sshStderrFile

                $deadline = [System.Diagnostics.Stopwatch]::StartNew()
                $listenerReady = $false
                while ($deadline.Elapsed.TotalSeconds -lt 20) {
                    Start-Sleep -Milliseconds 250
                    if ($tunnelProcess.HasExited) { break }
                    if (Get-NetTCPConnection -LocalPort 18000 -State Listen -ErrorAction SilentlyContinue) {
                        $listenerReady = $true
                        break
                    }
                }

                if (-not $listenerReady) {
                    $rawErr = ""
                    if (Test-Path -LiteralPath $sshStderrFile) {
                        $rawErr = (Get-Content -LiteralPath $sshStderrFile -Raw -ErrorAction SilentlyContinue)
                    }
                    if ($tunnelProcess.HasExited) {
                        if ($rawErr -match "Permission denied|Authentication failed") {
                            throw "SSH_AUTH_FAILED: VENOM SSH key authentication rejected by host"
                        } elseif ($rawErr -match "Host key verification failed") {
                            throw "SSH_HOST_KEY_FAILED: VENOM host key verification failed"
                        } elseif ($rawErr -match "Could not resolve hostname|Network is unreachable|Connection refused|Connection timed out|No route to host") {
                            throw "SSH_HOST_UNREACHABLE: VENOM host at 192.162.1.25 is unreachable"
                        } elseif ($rawErr -match "cannot listen to port|Address already in use") {
                            throw "LOCAL_PORT_CONFLICT: Local port 18000 cannot be bound by SSH"
                        } elseif ($rawErr -match "forwarding failed|remote port forwarding failed") {
                            throw "SSH_FORWARD_FAILED: Port forwarding to VENOM 127.0.0.1:8000 failed"
                        } else {
                            throw "SSH_PROCESS_EXITED: SSH tunnel process terminated prematurely"
                        }
                    } else {
                        throw "SSH_TIMEOUT: VENOM loopback tunnel did not become ready within 20s deadline"
                    }
                }
            } finally {
                if (Test-Path -LiteralPath $sshStderrFile) {
                    Remove-Item -LiteralPath $sshStderrFile -Force -ErrorAction SilentlyContinue
                }
            }
        }

        # Verify Core reachability through the active tunnel before starting physical acceptance
        $coreReachable = $false
        $coreProbeDeadline = [System.Diagnostics.Stopwatch]::StartNew()
        while ($coreProbeDeadline.Elapsed.TotalSeconds -lt 10) {
            try {
                $liveProbe = Invoke-RestMethod -Uri "http://127.0.0.1:18000/health/live" -TimeoutSec 2 -ErrorAction Stop
                if ($liveProbe.status -eq "ok") {
                    $coreReachable = $true
                    break
                }
            } catch {
                Start-Sleep -Milliseconds 500
            }
        }
        if (-not $coreReachable) {
            throw "CORE_UNREACHABLE_OVER_TUNNEL: Local tunnel port 18000 is listening but VENOM Core did not answer /health/live"
        }
    }
    $arguments = @(
        (Join-Path $repo "scripts\phase_10\run_physical_gate.py"),
        "--core-url", $coreUrl,
        "--wake-word-backend", "cascade_openwakeword_whisper",
        "--wake-word-model", $heyJarvisModel,
        "--wake-word-threshold", "0.20",
        "--wake-required-hits", "1",
        "--wake-temporal-policy", "moving_max",
        "--wake-temporal-window-frames", "3",
        "--wake-deactivation-threshold", "0.05",
        "--wake-vad-threshold", "0.35",
        "--wake-verifier-model", $wakeVerifier,
        "--wake-verifier-device", "cuda",
        "--wake-verifier-compute-type", "float16",
        "--stt-model", $stt,
        "--arabic-tts-model", (Join-Path $arabicRoot "ar_JO-kareem-medium.onnx"),
        "--arabic-tts-tokens", (Join-Path $arabicRoot "tokens.txt"),
        "--english-tts-model", (Join-Path $englishRoot "en_US-lessac-medium.onnx"),
        "--english-tts-tokens", (Join-Path $englishRoot "tokens.txt"),
        "--tts-data-dir", $ttsData,
        "--cuda-runtime-path", $cudaRoot.FullName,
        "--privacy-root", (Join-Path $env:LOCALAPPDATA "BMO\WindowsSatellite"),
        "--output", $output,
        "--wake-rounds", "3",
        "--software-tested-commit", $commit
    )
    if (-not [string]::IsNullOrWhiteSpace($sessionId)) {
        $arguments += @("--session-id", $sessionId)
    }
    if (-not [string]::IsNullOrWhiteSpace($inputDevice)) {
        $arguments += @("--input-device", $inputDevice)
    }
    if (-not [string]::IsNullOrWhiteSpace($outputDevice)) {
        $arguments += @("--output-device", $outputDevice)
    }
    if ($resumeStageA -eq "1") {
        $arguments += "--resume-stage-a"
    }
    & uv run --python 3.12 --extra voice python @arguments
    $exitCode = $LASTEXITCODE
} finally {
    if ($null -ne $tunnelProcess -and -not $tunnelProcess.HasExited) {
        Stop-Process -Id $tunnelProcess.Id -Force -ErrorAction SilentlyContinue
    }
}
exit $exitCode
