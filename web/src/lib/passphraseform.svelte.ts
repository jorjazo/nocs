// Rig's form to change the owner passphrase, which "This computer" opens when the SSH
// login's password is not the passphrase (ADR 0043).

export const passphraseForm = $state({
  open: false,
  // Bumped to bring the form into view.
  shown: 0,
});

export function showPassphraseForm(): void {
  passphraseForm.open = true;
  passphraseForm.shown += 1;
}
