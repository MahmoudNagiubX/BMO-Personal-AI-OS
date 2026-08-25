<#
.SYNOPSIS
    Run the one-time local Hey Jarvis owner-verifier enrollment.

    This command captures only the bounded enrollment clips needed by the
    pinned openWakeWord custom-verifier API.  The clips are temporary and are
    deleted before the command reports success.  The derived verifier and its
    sanitized manifest remain only under the Windows local application-data
    directory and are never written to Git.
#>
$ErrorActionPreference = "Stop"
$repo = (Resolve-Path (Join-Path $PSScriptRoot "../..")).Path
$model = Join-Path $repo ".venv\Lib\site-packages\openwakeword\resources\models\hey_jarvis_v0.1.onnx"
$profile = Join-Path $env:LOCALAPPDATA "BMO\voice\wake\hey_jarvis_owner_verifier"
if (-not (Test-Path -LiteralPath $model)) {
    throw "Official Hey Jarvis model is missing from the pinned openWakeWord package"
}
& uv run --python 3.12 --extra voice python (Join-Path $repo "scripts\phase_10\enroll_hey_jarvis_owner.py") `
    --model $model --profile-dir $profile
exit $LASTEXITCODE
