<#
.SYNOPSIS
    Run the short owner-local Phase 10 audio preflight.

The preflight opens the selected microphone and speaker, loads only the pinned
English TTS voice, verifies playback, and verifies simultaneous capture and
playback. PCM remains in memory and is never written to disk.
#>
$ErrorActionPreference = "Stop"
$repo = (Resolve-Path (Join-Path $PSScriptRoot "../..")).Path
$voiceRoot = Join-Path $env:LOCALAPPDATA "BMO\VoiceModels"
$englishRoot = Join-Path $voiceRoot "vits-piper-en_US-lessac-medium"
$englishModel = Join-Path $englishRoot "en_US-lessac-medium.onnx"
$englishTokens = Join-Path $englishRoot "tokens.txt"
$ttsData = Join-Path $voiceRoot "espeak-ng-data"
$inputDevice = [Environment]::GetEnvironmentVariable("BMO_VOICE_INPUT_DEVICE")
$outputDevice = [Environment]::GetEnvironmentVariable("BMO_VOICE_OUTPUT_DEVICE")
foreach ($required in @($englishModel, $englishTokens, $ttsData)) {
    if (-not (Test-Path -LiteralPath $required)) {
        throw "Required local audio preflight artifact is missing"
    }
}
$arguments = @(
    (Join-Path $repo "scripts\phase_10\run_audio_preflight.py"),
    "--english-tts-model", $englishModel,
    "--english-tts-tokens", $englishTokens,
    "--tts-data-dir", $ttsData
)
if (-not [string]::IsNullOrWhiteSpace($inputDevice)) {
    $arguments += @("--input-device", $inputDevice)
}
if (-not [string]::IsNullOrWhiteSpace($outputDevice)) {
    $arguments += @("--output-device", $outputDevice)
}
& uv run --python 3.12 --extra voice python @arguments
exit $LASTEXITCODE
