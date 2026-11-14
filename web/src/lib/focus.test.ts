import assert from "node:assert/strict";
import { test } from "node:test";
import { calibratedFor, estimateStep, roundStep, spread, unsteady } from "./focus.ts";

test("the estimate grows with the f-ratio and the focuser's resolution", () => {
  // The lab's EAF (47814 steps) on 380 mm / 81 mm: f/4.7.
  assert.equal(estimateStep(47814, 380 / 81), 110);
  assert.equal(estimateStep(47814, 10), 240);
  assert.equal(estimateStep(100000, 5), 250);
});

test("no estimate without the travel or the f-ratio", () => {
  assert.equal(estimateStep(null, 5), null);
  assert.equal(estimateStep(0, 5), null);
  assert.equal(estimateStep(47814, null), null);
});

test("steps are round numbers", () => {
  assert.equal(roundStep(112.3), 110);
  assert.equal(roundStep(3456), 3500);
  assert.equal(roundStep(7.4), 7);
  assert.equal(roundStep(0.2), 1);
});

test("a calibration counts for the profile it was measured with", () => {
  assert.equal(calibratedFor({ profile: "william" }, "william"), true);
  assert.equal(calibratedFor({ profile: "william" }, "redcat"), false);
  assert.equal(calibratedFor({ profile: null }, "william"), false);
  assert.equal(calibratedFor(null, "william"), false);
  assert.equal(calibratedFor({ profile: "william" }, null), false);
});

test("a backlash is unsteady when its measurements disagree", () => {
  assert.equal(spread([1000, 1450]), 450);
  assert.equal(spread([780]), 0);
  assert.equal(unsteady([780, 790], 12), false);
  assert.equal(unsteady([1000, 1450], 12), true);
  assert.equal(unsteady([10, 40], 12), false); // within 3 smallest steps
});
