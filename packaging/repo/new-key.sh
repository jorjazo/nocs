#!/usr/bin/env bash
# Make the apt repository's signing key (ADR 0035): an Ed25519 key without a
# passphrase that lives only in CI. Its private half goes straight into the GitHub
# secret APT_SIGNING_KEY and is never written to disk outside a temporary
# GNUPGHOME; its public half goes to packaging/repo/nocs-archive-keyring.asc, which
# the nocs package ships and the repository serves.
#
#   packaging/repo/new-key.sh            make the key and set the secret (gh, as an admin)
#   NO_SECRET=1 packaging/repo/new-key.sh   print nothing secret, keep no key: a dry run
set -euo pipefail

here=$(cd "$(dirname "$0")" && pwd)
keyring=$here/nocs-archive-keyring.asc
home=$(mktemp -d)
trap 'rm -rf "$home"' EXIT
export GNUPGHOME=$home

uid="NOCS archive signing key <jorjazo@gmail.com>"
gpg --batch --quiet --passphrase '' --quick-generate-key "$uid" ed25519 sign 5y
fingerprint=$(gpg --batch --with-colons --list-keys "$uid" | awk -F: '/^fpr:/ {print $10; exit}')
echo "key $fingerprint"

if [[ ${NO_SECRET:-0} == 1 ]]; then
    echo "dry run: no secret set, no keyring written"
    exit 0
fi
gpg --batch --armor --export-secret-keys "$fingerprint" | gh secret set APT_SIGNING_KEY
gpg --batch --armor --export "$fingerprint" > "$keyring"
echo "secret APT_SIGNING_KEY set; public key in $keyring (commit it)"
