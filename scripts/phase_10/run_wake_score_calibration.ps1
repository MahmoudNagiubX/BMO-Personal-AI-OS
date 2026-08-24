<#
.SYNOPSIS
    Run the bounded owner-local bare-Jarvis score calibration.

Only scalar probabilities, levels, timings, scenarios, and digests are saved
under the user's temporary directory. Raw microphone PCM is never persisted.
#>
$ErrorActionPreference = "Stop"
$repo = (Resolve-Path (Join-Path $PSScriptRoot "../..")).Path
$voiceRoot = Join-Path $env:LOCALAPPDATA "BMO\VoiceModels"
$wake = Join-Path $voiceRoot "jarvis-microwakeword-synthetic-v0.1.tflite"
$wakeConfig = Join-Path $voiceRoot "jarvis-microwakeword-synthetic-v0.1.json"
$inputDevice = [Environment]::GetEnvironmentVariable("BMO_VOICE_INPUT_DEVICE")
$outputDevice = [Environment]::GetEnvironmentVariable("BMO_VOICE_OUTPUT_DEVICE")
$output = Join-Path $env:TEMP "bmo-phase10-wake-score-calibration.json"
foreach ($required in @($wake, $wakeConfig)) {
    if (-not (Test-Path -LiteralPath $required)) {
        throw "Required local wake calibration artifact is missing"
    }
}
$arguments = @(
    (Join-Path $repo "scripts\phase_10\run_wake_score_calibration.py"),
    "--wake-word-model", $wake,
    "--wake-word-config", $wakeConfig,
    "--output", $output
)
if (-not [string]::IsNullOrWhiteSpace($inputDevice)) {
    $arguments += @("--input-device", $inputDevice)
}
if (-not [string]::IsNullOrWhiteSpace($outputDevice)) {
    $arguments += @("--output-device", $outputDevice)
}
& uv run --python 3.12 --extra voice python @arguments
exit $LASTEXITCODE
