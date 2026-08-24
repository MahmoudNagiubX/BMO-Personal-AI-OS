<#
.SYNOPSIS
    Run sanitized local microWakeWord scorer diagnostics.

The default run uses only in-memory controlled probes. Add -IncludeMicrophone
for one short owner-local live-speech probe after the controlled result is
reviewed. No PCM is written to disk.
#>
param(
    [switch]$IncludeMicrophone
)
$ErrorActionPreference = "Stop"
$repo = (Resolve-Path (Join-Path $PSScriptRoot "../..")).Path
$voiceRoot = Join-Path $env:LOCALAPPDATA "BMO\VoiceModels"
$wake = Join-Path $voiceRoot "jarvis-microwakeword-synthetic-v0.1.tflite"
$wakeConfig = Join-Path $voiceRoot "jarvis-microwakeword-synthetic-v0.1.json"
$englishRoot = Join-Path $voiceRoot "vits-piper-en_US-lessac-medium"
$englishModel = Join-Path $englishRoot "en_US-lessac-medium.onnx"
$englishTokens = Join-Path $englishRoot "tokens.txt"
$ttsData = Join-Path $voiceRoot "espeak-ng-data"
$output = Join-Path $env:TEMP "bmo-phase10-microwakeword-scorer-debug.json"

foreach ($required in @($wake, $wakeConfig, $englishModel, $englishTokens, $ttsData)) {
    if (-not (Test-Path -LiteralPath $required)) {
        throw "Required local scorer diagnostic artifact is missing"
    }
}

$arguments = @(
    (Join-Path $repo "scripts\phase_10\debug_micro_wakeword_scorer.py"),
    "--wake-word-model", $wake,
    "--wake-word-config", $wakeConfig,
    "--english-tts-model", $englishModel,
    "--english-tts-tokens", $englishTokens,
    "--tts-data-dir", $ttsData,
    "--output", $output
)
$inputDevice = [Environment]::GetEnvironmentVariable("BMO_VOICE_INPUT_DEVICE")
$outputDevice = [Environment]::GetEnvironmentVariable("BMO_VOICE_OUTPUT_DEVICE")
if (-not [string]::IsNullOrWhiteSpace($inputDevice)) {
    $arguments += @("--input-device", $inputDevice)
}
if (-not [string]::IsNullOrWhiteSpace($outputDevice)) {
    $arguments += @("--output-device", $outputDevice)
}
if ($IncludeMicrophone) {
    $arguments += "--include-microphone"
}

& uv run --python 3.12 --extra voice python @arguments
exit $LASTEXITCODE
