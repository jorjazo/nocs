import assert from "node:assert/strict";
import { test } from "node:test";
import { advice, angleParts, hourAngle, outerRing, place, radius, rings, siderealTime, suggestedStart } from "./polar.ts";

test("knob advice follows the axis", () => {
  const above = advice({ altitude: 12, azimuth: -4, total: 12.6 }, 1);
  assert.equal(above.altitude, "lower");
  assert.equal(above.azimuth, "east");
  assert.equal(above.altitudeBy, 12);
  assert.equal(above.azimuthBy, 4);
  const below = advice({ altitude: -3, azimuth: 2, total: 3.6 }, 1);
  assert.equal(below.altitude, "raise");
  assert.equal(below.azimuth, "west");
});

test("a knob within tolerance/√2 is done", () => {
  const near = advice({ altitude: 0.6, azimuth: -0.7, total: 0.92 }, 1);
  assert.equal(near.altitude, "ok");
  assert.equal(near.azimuth, "ok");
  assert.equal(advice({ altitude: 0.8, azimuth: 0, total: 0.8 }, 1).altitude, "lower");
});

test("angles read in the unit that fits", () => {
  assert.deepEqual(angleParts(150), { value: 2.5, unit: "°", digits: 1 });
  assert.deepEqual(angleParts(-12.4), { value: 12.4, unit: "′", digits: 0 });
  assert.deepEqual(angleParts(4.26), { value: 4.26, unit: "′", digits: 1 });
  assert.deepEqual(angleParts(0.5), { value: 30, unit: "″", digits: 0 });
});

test("the target grows to fit the error", () => {
  assert.equal(outerRing([0.5], 1), 5);
  assert.equal(outerRing([12], 1), 15);
  assert.equal(outerRing([200], 1), 300);
  assert.equal(outerRing([2000], 1), 2340);
  assert.deepEqual(rings(60, 1), [1, 5, 15, 30, 60]);
  assert.deepEqual(rings(5, 1), [1, 5]);
});

test("the radius is logarithmic and capped", () => {
  assert.equal(radius(0, 60, 1), 0);
  assert.equal(radius(60, 60, 1), 1);
  assert.equal(radius(600, 60, 1), 1);
  assert.ok(radius(1, 60, 1) > 0.15, "the tolerance ring keeps some room");
});

test("east is right in the north and left in the south", () => {
  const error = { altitude: 0, azimuth: 10, total: 10 };
  assert.ok(place(error, 15, 1, 45).x > 0);
  assert.ok(place(error, 15, 1, -30).x < 0);
  assert.ok(place({ altitude: 5, azimuth: 0, total: 5 }, 15, 1, -30).y > 0);
  assert.deepEqual(place({ altitude: 0, azimuth: 0, total: 0 }, 15, 1, -30), { x: 0, y: 0 });
});

test("sidereal time at J2000 and a known date", () => {
  assert.ok(Math.abs(siderealTime(new Date("2000-01-01T12:00:00Z"), 0) - 18.697374558) < 1e-6);
  // 2026-11-01 00:00 UT: GMST 2.686510 h (ERFA's gmst06).
  assert.ok(Math.abs(siderealTime(new Date("2026-11-01T00:00:00Z"), 0) - 2.68651) < 2 / 3600);
});

test("the suggested start is half an hour east, halfway to the pole", () => {
  const when = new Date("2026-11-01T03:00:00Z");
  const south = suggestedStart(-30.0277, -70.6733, when);
  assert.equal(south.dec, -60.01385);
  assert.ok(Math.abs(hourAngle(south.ra, when, -70.6733) + 0.5) < 1e-9);
  assert.equal(suggestedStart(40, 0, when).dec, 65);
});
