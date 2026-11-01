import assert from "node:assert/strict";
import { test } from "node:test";
import { estimateStep, roundStep } from "./focus.ts";

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
