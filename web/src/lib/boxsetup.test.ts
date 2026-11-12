import assert from "node:assert/strict";
import { test } from "node:test";
import { hostName, setupSteps, siteProblem, wifiPassword } from "./boxsetup.ts";

test("the name is a step only where the box can be renamed, the site always, and the review is last", () => {
  assert.deepEqual(setupSteps({ rename: true }), ["accessPoint", "wifi", "name", "site", "review"]);
  assert.deepEqual(setupSteps({ rename: false }), ["accessPoint", "wifi", "site", "review"]);
});

test("the site may be left for later or a saved one chosen; a new one needs a name and a position", () => {
  assert.equal(siteProblem(null), null);
  assert.equal(siteProblem({ saved: "abc12345" }), null);
  const draft = { name: "Backyard", latitude: -30, longitude: -70.7, elevation: null };
  assert.equal(siteProblem({ new: draft }), null);
  assert.equal(siteProblem({ new: { ...draft, name: "  " } }), "name");
  assert.equal(siteProblem({ new: { ...draft, latitude: null } }), "position");
  assert.equal(siteProblem({ new: { ...draft, longitude: null } }), "position");
});

test("host names are checked as nocs-system checks them", () => {
  assert.equal(hostName(" Rig-West "), "rig-west");
  assert.equal(hostName("nocs2"), "nocs2");
  assert.equal(hostName("x".repeat(63)), "x".repeat(63));
  for (const bad of ["", "rig west", "-rig", "rig-", "rig.local", "x".repeat(64), "ñandú"]) {
    assert.equal(hostName(bad), null, bad);
  }
});

test("Wi-Fi passwords are 8 to 63 ASCII characters, as nocs-system takes them", () => {
  assert.equal(wifiPassword("nocsnocs"), null);
  assert.equal(wifiPassword("dark skies!"), null);
  assert.equal(wifiPassword("1234567"), "short");
  assert.equal(wifiPassword("x".repeat(64)), "long");
  assert.equal(wifiPassword("contraseña"), "ascii");
  assert.equal(wifiPassword("tab\there!"), "ascii");
  assert.equal(wifiPassword("del\x7fdel!"), null); // as nocs-system takes it
});
