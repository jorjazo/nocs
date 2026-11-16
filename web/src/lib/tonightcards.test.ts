import assert from "node:assert/strict";
import { test } from "node:test";
import {
  coolerOffTarget,
  forecastHours,
  frameRadius,
  inputAttention,
  movedFrom,
  pointedAt,
  settledBy,
} from "./tonightcards.ts";
import type { ForecastHour, PlannedTarget, SkyPointing } from "./types.ts";

const M42: PlannedTarget = { id: "NGC 1976", name: "M 42", ra: 5.588, dec: -5.391 };

function object(label: string): SkyPointing["objects"][number] {
  return {
    id: label,
    label,
    type: "galaxy",
    ra: 0,
    dec: 0,
    constellation: null,
    magnitude: null,
    major_axis: null,
    minor_axis: null,
    position_angle: null,
    aliases: [],
    names: [],
    names_es: [],
  };
}

test("tonight's target first, then the Sun or the Moon, then the catalog", () => {
  const near = { ra: 5.6, dec: -5.4 };
  const around: SkyPointing = { body: null, objects: [object("NGC 1977")] };
  assert.equal(pointedAt(near, 0.5, M42, around).kind, "planned");
  assert.deepEqual(pointedAt({ ra: 7, dec: 0 }, 0.5, M42, around), { kind: "catalog", object: around.objects[0] });
  assert.deepEqual(pointedAt({ ra: 7, dec: 0 }, 0.5, M42, { body: "moon", objects: around.objects }), {
    kind: "body",
    body: "moon",
  });
  assert.deepEqual(pointedAt({ ra: 7, dec: 0 }, 0.5, null, { body: null, objects: [] }), { kind: "none" });
  assert.deepEqual(pointedAt({ ra: 7, dec: 0 }, 0.5, null, null), { kind: "none" });
});

test("a frame's reach and when to ask again", () => {
  assert.equal(frameRadius({ width: 3, height: 4 }), 2.5);
  assert.equal(frameRadius(null), 0.5);
  assert.equal(movedFrom(null, { ra: 1, dec: 0 }, 1), true);
  assert.equal(movedFrom({ ra: 1, dec: 0 }, { ra: 1, dec: 0.2 }, 1), false);
  assert.equal(movedFrom({ ra: 1, dec: 0 }, { ra: 1, dec: 0.3 }, 1), true);
});

test("the cooler is off target only once its ramp had time", () => {
  // From 20 °C to −10 °C at 3 °C/min: 10 minutes, and 5 more.
  const start = { at: 0, temperature: 20, target: -10 };
  assert.equal(settledBy(start, 3), 15 * 60_000);
  assert.equal(settledBy(start, 0), 5 * 60_000);
  assert.equal(coolerOffTarget(start, 0, 3, 14 * 60_000), false);
  assert.equal(coolerOffTarget(start, 0, 3, 15 * 60_000), true);
  assert.equal(coolerOffTarget(start, -9.5, 3, 60 * 60_000), false);
  assert.equal(coolerOffTarget(null, 0, 3, 60 * 60_000), false);
});

test("a battery's voltage", () => {
  assert.equal(inputAttention(12.6), null);
  assert.equal(inputAttention(11.9), "warning");
  assert.equal(inputAttention(11.4), "problem");
  assert.equal(inputAttention(null), null);
  assert.equal(inputAttention(0), null);
});

test("forecast hours from the current one to the end of the dark", () => {
  const hour = (iso: string): ForecastHour => ({
    time: iso,
    temperature: null,
    humidity: null,
    precipitation: null,
    precipitation_probability: null,
    cloud_cover: null,
    cloud_low: null,
    cloud_mid: null,
    cloud_high: null,
    wind_speed: null,
    wind_gusts: null,
  });
  const hours = ["21", "22", "23"].map((h) => hour(`2026-11-15T${h}:00:00+00:00`));
  const now = Date.parse("2026-11-15T21:40:00Z");
  assert.deepEqual(
    forecastHours(hours, now, Date.parse("2026-11-15T23:00:00Z")).map((h) => h.time),
    ["2026-11-15T21:00:00+00:00", "2026-11-15T22:00:00+00:00"],
  );
  // After the dark: the current hour still.
  assert.equal(forecastHours(hours, now, 0).length, 1);
});
