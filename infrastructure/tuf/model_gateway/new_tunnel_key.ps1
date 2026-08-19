[CmdletBinding()]
param(
    [string]$KeyPath = (Join-Path $env:USERPROFILE '.ssh\venom_model_tunnel_ed25519')
)

$ErrorActionPreference = 'Stop'
$sshKeygen = Join-Path $env:WINDIR 'System32\OpenSSH\ssh-keygen.exe'
if (-not (Test-Path -LiteralPath $sshKeygen -PathType Leaf)) {
    throw 'Windows OpenSSH key generation is unavailable.'
}
$publicKeyPath = "$KeyPath.pub"
if ((Test-Path -LiteralPath $KeyPath) -xor (Test-Path -LiteralPath $publicKeyPath)) {
    throw 'Only one half of the dedicated tunnel key pair exists; refusing to overwrite it.'
}
if (-not (Test-Path -LiteralPath $KeyPath)) {
    New-Item -ItemType Directory -Path (Split-Path -Parent $KeyPath) -Force | Out-Null
    # Windows PowerShell 5.1 drops a native empty-string argument. The quoted empty
    # argument is parsed by ssh-keygen as the required empty passphrase value.
    & $sshKeygen -q -t ed25519 -N '""' -C 'bmo-phase05b-tunnel' -f $KeyPath
    if ($LASTEXITCODE -ne 0) { throw 'Dedicated tunnel key generation failed.' }
}
$publicKey = (Get-Content -LiteralPath $publicKeyPath -Raw).Trim()
if ($publicKey -notmatch '^ssh-ed25519 [A-Za-z0-9+/=]+ bmo-phase05b-tunnel$') {
    throw 'The dedicated tunnel public key has an unexpected format.'
}
Write-Output "PHASE_05B_TUNNEL_KEY_READY public_key_path=$publicKeyPath"
