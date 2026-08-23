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
$wake = Join-Path $voiceRoot "jarvis-microwakeword-synthetic-v0.1.tflite"
$wakeConfig = Join-Path $voiceRoot "jarvis-microwakeword-synthetic-v0.1.json"
$stt = Join-Path $voiceRoot "faster-whisper-medium"
$arabicRoot = Join-Path $voiceRoot "vits-piper-ar_JO-kareem-medium"
$englishRoot = Join-Path $voiceRoot "vits-piper-en_US-lessac-medium"
$ttsData = Join-Path $voiceRoot "espeak-ng-data"
$cudaRoot = Get-ChildItem (Join-Path $env:LOCALAPPDATA "BMO\llama.cpp") -Directory -Recurse |
    Where-Object { Test-Path (Join-Path $_.FullName "cudart64_12.dll") } |
    Select-Object -First 1
$sessionId = [Environment]::GetEnvironmentVariable("BMO_VOICE_SESSION_ID")
$inputDevice = [Environment]::GetEnvironmentVariable("BMO_VOICE_INPUT_DEVICE")
$outputDevice = [Environment]::GetEnvironmentVariable("BMO_VOICE_OUTPUT_DEVICE")
$resumeStageA = [Environment]::GetEnvironmentVariable("BMO_VOICE_RESUME_STAGE_A")
$configuredCoreUrl = [Environment]::GetEnvironmentVariable("BMO_VOICE_CORE_URL")
$coreUrl = $configuredCoreUrl
$tunnelProcess = $null
$exitCode = 1
foreach ($required in @($wake, $wakeConfig, $stt, (Join-Path $arabicRoot "ar_JO-kareem-medium.onnx"), (Join-Path $arabicRoot "tokens.txt"), (Join-Path $englishRoot "en_US-lessac-medium.onnx"), (Join-Path $englishRoot "tokens.txt"), $ttsData)) {
    if (-not (Test-Path -LiteralPath $required)) { throw "Required local voice artifact is missing: $required" }
}
if ($null -eq $cudaRoot) { throw "No local CUDA runtime directory was found" }
$commit = (& git -C $repo rev-parse HEAD).Trim()
if ($commit -notmatch '^[0-9a-f]{40}$') { throw "Unable to resolve the exact physical-tested commit" }
$output = Join-Path $repo "docs\phase_reports\evidence\PHASE_10_JARVIS_VOICE_CORE.json"
try {
    if ([string]::IsNullOrWhiteSpace($configuredCoreUrl)) {
        $coreUrl = "http://127.0.0.1:18000"
        $existing = Get-NetTCPConnection -LocalPort 18000 -State Listen -ErrorAction SilentlyContinue
        if ($null -eq $existing) {
            $key = Join-Path $env:USERPROFILE ".ssh\venom_ed25519"
            if (-not (Test-Path -LiteralPath $key)) { throw "Verified VENOM SSH key is missing" }
            $tunnelProcess = Start-Process -FilePath ssh.exe -WindowStyle Hidden -PassThru -ArgumentList @(
                "-N", "-L", "18000:127.0.0.1:8000", "-o", "BatchMode=yes",
                "-o", "ExitOnForwardFailure=yes", "-o", "ConnectTimeout=10",
                "-o", "LogLevel=ERROR", "-i", $key, "venom@192.162.1.25"
            )
            for ($attempt = 0; $attempt -lt 20; $attempt++) {
                Start-Sleep -Milliseconds 250
                if ($tunnelProcess.HasExited) { throw "VENOM loopback tunnel exited before readiness" }
                if (Get-NetTCPConnection -LocalPort 18000 -State Listen -ErrorAction SilentlyContinue) { break }
            }
            if (-not (Get-NetTCPConnection -LocalPort 18000 -State Listen -ErrorAction SilentlyContinue)) {
                throw "VENOM loopback tunnel did not become ready"
            }
        }
    }
    $arguments = @(
        (Join-Path $repo "scripts\phase_10\run_physical_gate.py"),
        "--core-url", $coreUrl,
        "--wake-word-model", $wake,
        "--wake-word-config", $wakeConfig,
        "--stt-model", $stt,
        "--arabic-tts-model", (Join-Path $arabicRoot "ar_JO-kareem-medium.onnx"),
        "--arabic-tts-tokens", (Join-Path $arabicRoot "tokens.txt"),
        "--english-tts-model", (Join-Path $englishRoot "en_US-lessac-medium.onnx"),
        "--english-tts-tokens", (Join-Path $englishRoot "tokens.txt"),
        "--tts-data-dir", $ttsData,
        "--cuda-runtime-path", $cudaRoot.FullName,
        "--privacy-root", (Join-Path $env:LOCALAPPDATA "BMO\WindowsSatellite"),
        "--output", $output,
        "--wake-rounds", "20",
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
