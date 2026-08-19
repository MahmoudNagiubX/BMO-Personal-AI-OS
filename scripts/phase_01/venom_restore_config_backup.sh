#!/usr/bin/env bash
set -euo pipefail

# Restore proof runs on VENOM and never leaves plaintext outside this temporary
# directory.  The GPG passphrase is intentionally requested by gpg on the
# attached terminal; it is never accepted as an argument or environment value.
readonly encrypted_path="/tmp/venom-phase1-config-from-tuf.tar.gz.gpg"
readonly checksum_path="/tmp/venom-phase1-config.tar.gz.sha256"
readonly restore_dir="/tmp/venom-phase1-restore-from-tuf"
readonly archive_path="$restore_dir/venom-phase1-config.tar.gz"
readonly extract_dir="$restore_dir/extracted"

cleanup() {
  rm -rf "$restore_dir"
}
trap cleanup EXIT

[[ -r "$encrypted_path" ]] || { printf 'MISSING_ENCRYPTED_ARCHIVE\n' >&2; exit 1; }
[[ -r "$checksum_path" ]] || { printf 'MISSING_ARCHIVE_CHECKSUM\n' >&2; exit 1; }

mkdir -p "$extract_dir"
chmod 700 "$restore_dir"
gpg --decrypt --pinentry-mode loopback --output "$archive_path" "$encrypted_path"

expected_checksum="$(awk '{print $1}' "$checksum_path")"
actual_checksum="$(sha256sum "$archive_path" | awk '{print $1}')"
[[ "$expected_checksum" == "$actual_checksum" ]] || {
  printf 'BACKUP_RESTORE_CHECKSUM_MISMATCH\n' >&2
  exit 1
}

tar -xzf "$archive_path" -C "$extract_dir"
file_count="$(find "$extract_dir" -type f -print | wc -l)"
(( file_count >= 10 )) || {
  printf 'BACKUP_RESTORE_CONTENT_INCOMPLETE FILES=%s\n' "$file_count" >&2
  exit 1
}

printf 'BACKUP_RESTORE_PASS FILES=%s\n' "$file_count"
