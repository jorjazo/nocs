import assert from "node:assert/strict";
import { test } from "node:test";
import { BACKGROUNDS, calibrated, folded, nearest, outcome, parts } from "./stack.ts";
import type { CurrentStack, StackOutcome } from "./types";

const LAST: StackOutcome = {
  accepted: true,
  reason: null,
  cause: null,
  shift: [3, 4],
  rotation: 0.2,
  stars: 40,
  rms: 0.1,
  clipped: 0,
  hot_pixels: null,
  seconds: 1.2,
  time: "2026-11-08T23:00:00+00:00",
  frame_id: 7,
};

function stack(dark: boolean, flat: boolean, cosmetic: boolean): CurrentStack {
  return {
    id: "s",
    started: "2026-11-08T23:00:00+00:00",
    frames: 3,
    rejected: 0,
    skipped: 0,
    exposure: 90,
    camera: "CCD",
    target: null,
    filter: null,
    setup: { exposure: 30, gain: 100, offset: 50, binning: 1, width: 6248, height: 4176, colour: true },
    calibration: {
      dark,
      flat,
      cosmetic,
      notes: [],
      dark_kind: dark ? "dark" : null,
      dark_frames: dark ? 20 : 0,
      flat_frames: flat ? 15 : 0,
      flats_unused: false,
    },
    last: LAST,
    preview: null,
  };
}

test("a look between presets shows as the nearest step", () => {
  assert.equal(nearest(BACKGROUNDS, 0.26), 0.25);
  assert.equal(nearest(BACKGROUNDS, 0.9), 0.4);
  assert.equal(nearest(BACKGROUNDS, 0), 0.15);
});

test("calibration in one word", () => {
  assert.equal(calibrated(stack(true, true, false)), "darksFlats");
  assert.equal(calibrated(stack(true, false, false)), "darks");
  assert.equal(calibrated(stack(false, true, true)), "flats");
  assert.equal(calibrated(stack(false, false, true)), "cosmetic");
  assert.equal(calibrated(stack(false, false, false)), "none");
});

test("the latest frame: how far it moved, or why it was left out", () => {
  assert.deepEqual(outcome(LAST), { kind: "accepted", shift: 5, rotation: 0.2 });
  const left = { ...LAST, accepted: false, cause: "registration" as const, reason: "no star pattern" };
  assert.deepEqual(outcome(left), { kind: "left", cause: "registration", reason: "no star pattern" });
});

test("a meridian flip folds to ±180°", () => {
  assert.equal(folded(179.5), 179.5);
  assert.equal(folded(-179.5), -179.5);
  assert.equal(folded(190), -170);
  assert.ok(Math.abs(folded(-0.2) + 0.2) < 1e-9);
});

test("the calibration's parts", () => {
  assert.deepEqual(parts(stack(true, true, false)), [
    { kind: "darks", count: 20 },
    { kind: "flats", count: 15 },
  ]);
  const bias = stack(false, false, true);
  bias.calibration = { ...bias.calibration, dark_kind: "bias", dark_frames: 12, flats_unused: true };
  assert.deepEqual(parts(bias), [{ kind: "bias", count: 12 }, { kind: "flatsUnused" }]);
  assert.deepEqual(parts(stack(false, false, true)), [{ kind: "noDarks" }, { kind: "noFlats" }]);
});
