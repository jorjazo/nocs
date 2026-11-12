import assert from "node:assert/strict";
import { test } from "node:test";
import { hostName, setupSteps, wifiPassword } from "./boxsetup.ts";

test("the name is a step only where the box can be renamed, and the review is last", () => {
  assert.deepEqual(setupSteps({ rename: true }), ["accessPoint", "wifi", "name", "review"]);
  assert.deepEqual(setupSteps({ rename: false }), ["accessPoint", "wifi", "review"]);
});

test("host names are checked as nocs-system checks them", () => {
  assert.equal(hostName(" Rig-West "), "rig-west");
  assert.equal(hostName("nocs2"), "nocs2");
  assert.equal(hostName("x".repeat(63)), "x".repeat(63));
  for (const bad of ["", "rig west", "-rig", "rig-", "rig.local", "x".repeat(64), "ñandú"]) {
    assert.equal(hostName(bad), null, bad);
  }
});

test("Wi-Fi passwords are 8 to 63 printable ASCII characters", () => {
  assert.equal(wifiPassword("nocsnocs"), null);
  assert.equal(wifiPassword("dark skies!"), null);
  assert.equal(wifiPassword("1234567"), "short");
  assert.equal(wifiPassword("x".repeat(64)), "long");
  assert.equal(wifiPassword("contraseña"), "ascii");
});
