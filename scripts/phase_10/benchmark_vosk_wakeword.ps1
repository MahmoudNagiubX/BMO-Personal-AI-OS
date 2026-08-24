param(
    [Parameter(Mandatory = $false)]
    [string]$ModelPath = (Join-Path $env:LOCALAPPDATA "BMO\VoiceModels\vosk-model-small-en-us-0.15"),
    [Parameter(Mandatory = $false)]
    [string]$OutputPath = (Join-Path $env:TEMP "bmo-phase10-vosk-wake-benchmark.json")
)

$ErrorActionPreference = "Stop"
$voiceRoot = Join-Path $env:LOCALAPPDATA "BMO\VoiceModels"
$ttsRoot = Join-Path $voiceRoot "vits-piper-en_US-lessac-medium"
$ttsModel = Join-Path $ttsRoot "en_US-lessac-medium.onnx"
$ttsTokens = Join-Path $ttsRoot "tokens.txt"
$ttsData = Join-Path $voiceRoot "espeak-ng-data"

foreach ($path in @($ModelPath, $ttsModel, $ttsTokens, $ttsData)) {
    if (-not (Test-Path -LiteralPath $path)) {
        throw "Required local voice artifact is missing: $([IO.Path]::GetFileName($path))"
    }
}

uv run --extra voice python scripts/phase_10/benchmark_vosk_wakeword.py `
    --model $ModelPath `
    --english-tts-model $ttsModel `
    --english-tts-tokens $ttsTokens `
    --tts-data-dir $ttsData `
    --output $OutputPath
