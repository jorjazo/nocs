// The owner passphrase's rules as nocsd checks them (ADR 0014), and the appliance's
// SSH login whose password follows it (ADR 0043).

import type { SystemLogin } from "./types";

export const MIN_PASSPHRASE = 8;
export const MAX_PASSPHRASE = 1024;

// Characters as the server counts them: code points after NFC normalization.
export function passphraseLength(passphrase: string): number {
  return [...passphrase.normalize("NFC")].length;
}

export function passphraseRule(passphrase: string): "tooShort" | "tooLong" | null {
  const length = passphraseLength(passphrase);
  if (length < MIN_PASSPHRASE) return "tooShort";
  if (length > MAX_PASSPHRASE) return "tooLong";
  return null;
}

export type PassphraseChange = { current: string; next: string; again: string };

export type ChangeProblems = {
  current?: "missing";
  next?: "tooShort" | "tooLong";
  again?: "mismatch";
};

// What keeps a change of passphrase from being sent, by field; empty when nothing
// does. The new passphrase may equal the current one: entering it again sets the
// SSH login's password when it is not set yet.
export function changeProblems(change: PassphraseChange): ChangeProblems {
  const problems: ChangeProblems = {};
  if (!change.current) problems.current = "missing";
  const rule = passphraseRule(change.next);
  if (rule) problems.next = rule;
  else if (change.again.normalize("NFC") !== change.next.normalize("NFC")) problems.again = "mismatch";
  return problems;
}

// What the owner should hear about the SSH login: nothing while its password is the
// passphrase, or where there is no login (a PC).
export function loginWarning(login: SystemLogin | null | undefined): "locked" | "failed" | null {
  if (!login || login.password === "set") return null;
  return login.password;
}
