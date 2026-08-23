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
$coreUrl = [Environment]::GetEnvironmentVariable("BMO_VOICE_CORE_URL")
if ([string]::IsNullOrWhiteSpace($coreUrl)) { $coreUrl = "http://192.162.1.25:8000" }
foreach ($required in @($wake, $wakeConfig, $stt, (Join-Path $arabicRoot "ar_JO-kareem-medium.onnx"), (Join-Path $arabicRoot "tokens.txt"), (Join-Path $englishRoot "en_US-lessac-medium.onnx"), (Join-Path $englishRoot "tokens.txt"), $ttsData)) {
    if (-not (Test-Path -LiteralPath $required)) { throw "Required local voice artifact is missing: $required" }
}
if ($null -eq $cudaRoot) { throw "No local CUDA runtime directory was found" }
$commit = (& git -C $repo rev-parse HEAD).Trim()
if ($commit -notmatch '^[0-9a-f]{40}$') { throw "Unable to resolve the exact physical-tested commit" }
$output = Join-Path $repo "docs\phase_reports\evidence\PHASE_10_JARVIS_VOICE_CORE.json"
& uv run --python 3.12 --extra voice python (Join-Path $repo "scripts\phase_10\run_physical_gate.py") `
    --core-url $coreUrl `
    --session-id $sessionId `
    --wake-word-model $wake `
    --wake-word-config $wakeConfig `
    --stt-model $stt `
    --arabic-tts-model (Join-Path $arabicRoot "ar_JO-kareem-medium.onnx") `
    --arabic-tts-tokens (Join-Path $arabicRoot "tokens.txt") `
    --english-tts-model (Join-Path $englishRoot "en_US-lessac-medium.onnx") `
    --english-tts-tokens (Join-Path $englishRoot "tokens.txt") `
    --tts-data-dir $ttsData `
    --cuda-runtime-path $cudaRoot.FullName `
    --privacy-root (Join-Path $env:LOCALAPPDATA "BMO\WindowsSatellite") `
    --output $output `
    --wake-rounds 20 `
    --software-tested-commit $commit
exit $LASTEXITCODE
