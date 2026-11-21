import assert from "node:assert/strict";
import { test } from "node:test";
import { droppedShare, recordingBytes, regionAt, regionSizes, sensorPoint } from "./video.ts";

const SENSOR = { width: 6248, height: 4176 };

test("only region sizes smaller than the sensor are offered", () => {
  assert.deepEqual(
    regionSizes({ width: 1280, height: 1024 }).map((s) => s.width),
    [320, 640, 1024],
  );
  assert.equal(regionSizes(SENSOR).length, 4);
});

test("a region is centred where asked, inside the sensor, at even coordinates", () => {
  const size = { width: 640, height: 480 };
  assert.deepEqual(regionAt(3125, 2089, size, SENSOR), { x: 2804, y: 1848, width: 640, height: 480 });
  assert.deepEqual(regionAt(10, 10, size, SENSOR), { x: 0, y: 0, width: 640, height: 480 });
  assert.deepEqual(regionAt(6247, 4175, size, SENSOR), { x: 5608, y: 3696, width: 640, height: 480 });
});

test("a point on screen lies on the region read out, or on the whole sensor", () => {
  assert.deepEqual(sensorPoint({ x: 0.5, y: 0.5 }, null, SENSOR), { x: 3124, y: 2088 });
  const region = { x: 1000, y: 2000, width: 640, height: 480 };
  assert.deepEqual(sensorPoint({ x: 0.25, y: 1 }, region, SENSOR), { x: 1160, y: 2480 });
});

test("what a recording takes", () => {
  assert.equal(recordingBytes({ mode: "frames", value: 100 }, 307200, null), 178 + 100 * 307208);
  assert.equal(recordingBytes({ mode: "seconds", value: 10 }, 1000, 125), 178 + 1250 * 1008);
  assert.equal(recordingBytes({ mode: "seconds", value: 10 }, 1000, null), null);
});

test("the share of frames dropped", () => {
  assert.ok(Math.abs((droppedShare(90, 10) ?? 0) - 0.1) < 1e-9);
  assert.equal(droppedShare(100, null), null);
});
