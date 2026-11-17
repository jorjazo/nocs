import assert from "node:assert/strict";
import { test } from "node:test";
import { bands, darkLeft, light, nearest, phase, position } from "./night.ts";

const times = ["2026-11-15T23:00:00Z", "2026-11-15T23:10:00Z", "2026-11-15T23:20:00Z", "2026-11-15T23:30:00Z"];

test("twilight limits", () => {
  assert.equal(light(5), "day");
  assert.equal(light(-0.5), "day");
  assert.equal(light(-3), "civil");
  assert.equal(light(-6), "civil");
  assert.equal(light(-9), "nautical");
  assert.equal(light(-15), "astronomical");
  assert.equal(light(-30), "dark");
});

test("bands join samples with the same light and meet halfway", () => {
  const [civil, dark, ...rest] = bands(times, [-3, -4, -20, -25]);
  assert.ok(civil && dark);
  assert.equal(rest.length, 0);
  assert.deepEqual([civil.light, dark.light], ["civil", "dark"]);
  assert.equal(civil.start, Date.parse("2026-11-15T23:00:00Z"));
  assert.equal(civil.end, Date.parse("2026-11-15T23:15:00Z"));
  assert.equal(dark.start, civil.end);
  assert.equal(dark.end, Date.parse("2026-11-15T23:30:00Z"));
});

test("position on the night's axis", () => {
  assert.equal(position(5, 0, 10), 0.5);
  assert.equal(position(0, 0, 10), 0);
  assert.equal(position(11, 0, 10), null);
  assert.equal(position(1, 5, 5), null);
});

test("moon phases by angle", () => {
  assert.equal(phase(0), "new");
  assert.equal(phase(359), "new");
  assert.equal(phase(45), "waxingCrescent");
  assert.equal(phase(91), "firstQuarter");
  assert.equal(phase(180), "full");
  assert.equal(phase(250), "lastQuarter");
  assert.equal(phase(320), "waningCrescent");
  assert.equal(phase(-90), "lastQuarter");
});

test("nearest sample", () => {
  assert.equal(nearest(times, Date.parse("2026-11-15T23:14:00Z")), 1);
  assert.equal(nearest(times, Date.parse("2026-11-15T23:16:00Z")), 2);
  assert.equal(nearest(times, Date.parse("2026-11-15T22:00:00Z")), null);
  assert.equal(nearest([], 0), null);
});

test("the dark window before, during and after", () => {
  const dark = { start: "2026-11-16T01:00:00Z", end: "2026-11-16T07:00:00Z" };
  const at = (iso: string) => Date.parse(iso);
  assert.equal(darkLeft(null, [], at("2026-11-16T00:00:00Z")), null);
  assert.deepEqual(darkLeft(dark, null, at("2026-11-16T00:00:00Z")), { when: "before", in: 3600, length: 6 * 3600 });
  assert.deepEqual(darkLeft(dark, null, at("2026-11-16T04:00:00Z")), { when: "during", left: 3 * 3600, moonless: null });
  assert.deepEqual(darkLeft(dark, null, at("2026-11-16T07:00:00Z")), { when: "after" });
});

test("only what is left of the stretches without the Moon counts", () => {
  const dark = { start: "2026-11-16T01:00:00Z", end: "2026-11-16T07:00:00Z" };
  const moonless = [
    { start: "2026-11-16T01:00:00Z", end: "2026-11-16T02:00:00Z" },
    { start: "2026-11-16T05:00:00Z", end: "2026-11-16T07:00:00Z" },
  ];
  const left = (iso: string) => darkLeft(dark, moonless, Date.parse(iso));
  assert.deepEqual(left("2026-11-16T01:30:00Z"), { when: "during", left: 5.5 * 3600, moonless: 2.5 * 3600 });
  assert.deepEqual(left("2026-11-16T06:00:00Z"), { when: "during", left: 3600, moonless: 3600 });
  assert.deepEqual(darkLeft(dark, [], Date.parse("2026-11-16T03:00:00Z")), { when: "during", left: 4 * 3600, moonless: 0 });
});
