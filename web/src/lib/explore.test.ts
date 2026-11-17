import assert from "node:assert/strict";
import { test } from "node:test";
import { isOpen, parseOpen, solvedShown, stretched, untilMeridian } from "./explore.ts";
import { siderealTime } from "./polar.ts";

test("panes start open lying down and folded upright", () => {
  assert.equal(isOpen({}, "guiding", "landscape"), true);
  assert.equal(isOpen({}, "guiding", "portrait"), false);
  assert.equal(isOpen({}, "panel", "portrait"), false);
});

test("each orientation keeps its own choice", () => {
  const open = parseOpen(JSON.stringify({ "portrait.focus": true, "landscape.focus": false, junk: 3 }));
  assert.equal(isOpen(open, "focus", "portrait"), true);
  assert.equal(isOpen(open, "focus", "landscape"), false);
  assert.equal(isOpen(open, "goto", "portrait"), false);
  assert.deepEqual(parseOpen("not json"), {});
});

test("time to the meridian, in hours of the clock", () => {
  const when = new Date("2026-11-17T03:00:00Z");
  const longitude = -70.67;
  const lst = siderealTime(when, longitude);
  // Two sidereal hours east of the meridian: a little less on the clock.
  const east = untilMeridian((lst + 2) % 24, longitude, when);
  assert.ok(Math.abs(east - 2 * 0.99726957) < 1e-6);
  // Half an hour past it: negative.
  const west = untilMeridian((lst + 23.5) % 24, longitude, when);
  assert.ok(west < 0 && Math.abs(west + 0.5 * 0.99726957) < 1e-6);
});

test("a solution is of the frame on screen when its middle matches", () => {
  const preview = { time: "2026-11-17T03:00:30Z", exposure: 30 };
  assert.equal(solvedShown(preview, { taken: "2026-11-17T03:00:15Z" }), true);
  assert.equal(solvedShown(preview, { taken: "2026-11-17T02:59:45Z" }), false);
  assert.equal(solvedShown(preview, { taken: null }), false);
  assert.equal(solvedShown(null, { taken: "2026-11-17T03:00:15Z" }), false);
});

test("the stretch turns its shadows black and its midtones grey", () => {
  const stretch = { shadows: 0.01, midtones: 0.02 };
  assert.equal(stretched(0.005, stretch), 0);
  assert.ok(Math.abs(stretched(0.02, stretch) - 0.5) < 1e-9);
  assert.equal(stretched(1, stretch), 1);
});
