import assert from "node:assert/strict";
import { test } from "node:test";
import { changeProblems, loginWarning, passphraseLength, passphraseRule } from "./passphrase.ts";

test("characters are counted as the server counts them, after NFC", () => {
  // "é" as e + combining accent is two code points before NFC, one after.
  assert.equal(passphraseLength("café"), 4);
  assert.equal(passphraseLength("🔭🔭"), 2);
  assert.equal(passphraseRule("seven 7"), "tooShort");
  assert.equal(passphraseRule("ééééééé"), "tooShort");
  assert.equal(passphraseRule("eight 88"), null);
  assert.equal(passphraseRule("x".repeat(1025)), "tooLong");
});

test("a change needs the current passphrase, a valid new one, and the same one twice", () => {
  assert.deepEqual(changeProblems({ current: "", next: "short", again: "" }), { current: "missing", next: "tooShort" });
  assert.deepEqual(changeProblems({ current: "old passphrase", next: "new passphrase", again: "new passphrasE" }), {
    again: "mismatch",
  });
  assert.deepEqual(changeProblems({ current: "old passphrase", next: "new passphrase", again: "new passphrase" }), {});
  // Composed and decomposed forms are the same passphrase to the server.
  assert.deepEqual(changeProblems({ current: "old passphrase", next: "café olé!", again: "café olé!" }), {});
});

test("entering the current passphrase as the new one is allowed: it sets the SSH password", () => {
  assert.deepEqual(changeProblems({ current: "the passphrase", next: "the passphrase", again: "the passphrase" }), {});
});

test("the SSH login warns only when its password is not the passphrase", () => {
  assert.equal(loginWarning(null), null);
  assert.equal(loginWarning(undefined), null);
  assert.equal(loginWarning({ user: "nocs", password: "set" }), null);
  assert.equal(loginWarning({ user: "nocs", password: "locked" }), "locked");
  assert.equal(loginWarning({ user: "nocs", password: "failed" }), "failed");
});
