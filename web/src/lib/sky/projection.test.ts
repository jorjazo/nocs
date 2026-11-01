import assert from "node:assert/strict";
import { test } from "node:test";
import {
  axes,
  frameCorners,
  pan,
  project,
  scaleFor,
  screenAngle,
  separation,
  skyFrameCorners,
  unproject,
  type Sky,
  type View,
  viewRadius,
  viewSpan,
} from "./projection.ts";

function close(actual: number, expected: number, tolerance: number, what = ""): void {
  assert(Math.abs(actual - expected) <= tolerance, `${what} ${actual} is not ${expected} ± ${tolerance}`);
}

// NGC 253 and NGC 292 (the SMC): the phase's exit targets.
const NGC253: Sky = { ra: 0.7928, dec: -25.29 };
const SMC: Sky = { ra: 0.8768, dec: -72.83 };

function view(center: Sky, degrees = 4, width = 375, height = 600): View {
  return { center, scale: scaleFor(degrees, width, height), width, height };
}

test("the centre projects to the middle of the view", () => {
  const v = view(NGC253);
  const p = project(v, NGC253);
  assert(p);
  close(p.x, 187.5, 1e-9);
  close(p.y, 300, 1e-9);
});

test("north is up and east is left", () => {
  const v = view(NGC253);
  const north = project(v, { ra: NGC253.ra, dec: NGC253.dec + 1 });
  const east = project(v, { ra: NGC253.ra + 0.05, dec: NGC253.dec });
  assert(north && east);
  close(north.x, 187.5, 1e-9, "north x");
  assert(north.y < 300);
  assert(east.x < 187.5);
  close(east.y, 300, 3, "east y"); // a parallel bends slightly off the centre
});

test("projecting and unprojecting round-trips across 0h and near the pole", () => {
  for (const center of [NGC253, SMC, { ra: 23.98, dec: 10 }, { ra: 12, dec: -89.5 }]) {
    const v = view(center, 20);
    for (const point of [
      { x: 0, y: 0 },
      { x: 375, y: 600 },
      { x: 100, y: 450 },
    ]) {
      const sky = unproject(v, point);
      assert(sky.ra >= 0 && sky.ra < 24);
      const back = project(v, sky);
      assert(back);
      close(back.x, point.x, 1e-6, "x");
      close(back.y, point.y, 1e-6, "y");
    }
  }
});

test("distances on the chart match angles on the sky", () => {
  const v = view(NGC253, 2);
  // A degree north of the centre is (very nearly) a degree on the scale.
  const north = project(v, { ra: NGC253.ra, dec: NGC253.dec + 1 });
  assert(north);
  close((300 - north.y) / v.scale, Math.tan(Math.PI / 180), 1e-12);
  close(viewSpan(v), 2, 1e-9);
  close(viewRadius(v), separation(NGC253, unproject(v, { x: 0, y: 0 })), 1e-9);
});

test("points behind the view are not drawn", () => {
  assert.equal(project(view(NGC253), { ra: NGC253.ra + 12, dec: -NGC253.dec }), null);
});

function drag(v: View, from: { x: number; y: number }): View {
  // 80 px as pointer events report a drag, in steps of a few pixels.
  let moved = v;
  for (let i = 0; i < 16; i++) {
    const at = { x: from.x + 3 * i, y: from.y + 4 * i };
    moved = { ...moved, center: pan(moved, at, { x: at.x + 3, y: at.y + 4 }) };
  }
  return moved;
}

test("panning keeps the sky under the finger and stops short of the pole", () => {
  const from = { x: 100, y: 200 };
  const v = view(NGC253, 10);
  const now = project(drag(v, from), unproject(v, from));
  assert(now);
  close(now.x, 148, 1);
  close(now.y, 264, 1);
  // Near the pole, keeping north up turns the chart under the finger a little.
  const polar = view(SMC, 10);
  const there = project(drag(polar, from), unproject(polar, from));
  assert(there);
  close(there.x, 148, 6);
  close(there.y, 264, 6);

  // Dragging up again and again goes south, to the pole and no further.
  let south = polar;
  for (let i = 0; i < 100; i++) south = { ...south, center: pan(south, { x: 187, y: 300 }, { x: 187, y: 250 }) };
  close(south.center.dec, -89.9, 1e-9);
});

test("north turns off the centre and position angles follow it", () => {
  const v = view(SMC, 30);
  const centre = axes(v, SMC);
  assert(centre);
  close(centre.north.x, 0, 1e-6);
  close(centre.north.y, -1, 1e-6);
  close(centre.east.x, -1, 1e-6);
  // 10° east of the centre, near the south pole, north leans visibly.
  const off = axes(v, { ra: SMC.ra + 2.5, dec: SMC.dec });
  assert(off);
  assert(Math.abs(off.north.x) > 0.3);
  // A position angle of 0 points north; 90 points east (left).
  close(screenAngle(v, SMC, 0) ?? 0, -Math.PI / 2, 1e-6);
  close(Math.abs(screenAngle(v, SMC, 90) ?? 0), Math.PI, 1e-6);
});

test("the camera frame is a rectangle turned by its rotation", () => {
  // The simulator's camera on the 3.3 rig: about 1.3° × 0.9°.
  const v = view(NGC253, 3);
  const [topLeft, topRight, bottomRight, bottomLeft] = frameCorners(v, 1.3, 0.9, 0);
  assert(topLeft && topRight && bottomRight && bottomLeft);
  close(topLeft.y, topRight.y, 1e-9);
  assert(topLeft.y < bottomLeft.y);
  close(topRight.x - topLeft.x, 1.3 * (Math.PI / 180) * v.scale, 1e-9);
  close(bottomLeft.y - topLeft.y, 0.9 * (Math.PI / 180) * v.scale, 1e-9);

  // Turned 90° east of north: the top points east (left), the right side north.
  const [a, b, , d] = frameCorners(v, 1.3, 0.9, 90);
  assert(a && b && d);
  const top = { x: a.x - d.x, y: a.y - d.y };
  const right = { x: b.x - a.x, y: b.y - a.y };
  assert(top.x < 0);
  close(top.y, 0, 1e-9);
  assert(right.y < 0);
  close(right.x, 0, 1e-9);
});

test("a frame at the view's centre has the same corners either way", () => {
  const view: View = { center: { ra: 0.88, dec: -72.8 }, scale: scaleFor(4, 400, 600), width: 400, height: 600 };
  for (const rotation of [0, 30, 135, 290]) {
    const centred = frameCorners(view, 2.3, 1.5, rotation);
    const anywhere = skyFrameCorners(view, view.center, 2.3, 1.5, rotation);
    assert.ok(anywhere);
    centred.forEach((corner, i) => {
      const other = anywhere[i];
      assert.ok(other);
      close(other.x, corner.x, 0.5, `rotation ${rotation} corner ${i} x`);
      close(other.y, corner.y, 0.5, `rotation ${rotation} corner ${i} y`);
    });
  }
});
