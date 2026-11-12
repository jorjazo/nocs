import assert from "node:assert/strict";
import { test } from "node:test";
import { distance, gpsSource, mountSource, nearestSite } from "./sites.ts";
import type { GpsState, MountState, Site } from "./types.ts";

const saved: Record<string, Site> = {
  home: { name: "Home", latitude: -30.0277, longitude: -70.6733, elevation: 700 },
  dark: { name: "Dark site", latitude: -30.2, longitude: -70.5, elevation: 1500 },
};

// Only what the sources read of the mount's state.
function mount(site: MountState["site"]): MountState {
  return { site } as MountState;
}

function gps(fields: Partial<GpsState>): GpsState {
  return { connected: true, fix: "3d", latitude: null, longitude: null, elevation: null, time: null, site: null, ...fields };
}

test("distances are on the ground, as the server measures them", () => {
  assert.equal(distance(saved.home!, saved.home!), 0);
  // A degree of latitude is about 111 km.
  assert.ok(Math.abs(distance({ latitude: 0, longitude: 0 }, { latitude: 1, longitude: 0 }) - 111_195) < 1);
});

test("the nearest saved site within 500 m, leaving out the one being edited", () => {
  const nearHome = { latitude: -30.0297, longitude: -70.6733 }; // about 220 m south
  assert.equal(nearestSite(saved, nearHome), "home");
  assert.equal(nearestSite(saved, nearHome, "home"), null);
  assert.equal(nearestSite(saved, { latitude: -30.035, longitude: -70.6733 }), null); // about 810 m
  assert.equal(nearestSite({}, nearHome), null);
});

test("the mount gives its own site, unless it has none", () => {
  assert.deepEqual(mountSource(null, saved), { problem: "noMount" });
  assert.deepEqual(mountSource(mount(null), saved), { problem: "noMountSite" });
  assert.deepEqual(mountSource(mount({ latitude: 0, longitude: 0, elevation: 0 }), saved), { problem: "mountUnset" });
  assert.deepEqual(mountSource(mount({ latitude: 51.4778123456, longitude: -0.0014, elevation: 45.6 }), saved), {
    position: { latitude: 51.477812, longitude: -0.0014, elevation: 46 },
    near: null,
  });
  // Right after NOCS sent it the active site, the mount is there.
  assert.deepEqual(mountSource(mount({ latitude: -30.0277, longitude: -70.6733, elevation: 700 }), saved), {
    position: { latitude: -30.0277, longitude: -70.6733, elevation: 700 },
    near: "home",
  });
});

test("the GPS gives its fix: the elevation only with a 3D one", () => {
  assert.deepEqual(gpsSource(null, saved), { problem: "noGps" });
  assert.deepEqual(gpsSource(gps({ connected: false }), saved), { problem: "noGps" });
  assert.deepEqual(gpsSource(gps({ fix: "none" }), saved), { problem: "noFix" });
  assert.deepEqual(gpsSource(gps({ fix: "2d", latitude: -30.2, longitude: -70.5, elevation: null }), saved), {
    position: { latitude: -30.2, longitude: -70.5, elevation: null },
    near: "dark",
  });
  assert.deepEqual(gpsSource(gps({ latitude: -33.45, longitude: -70.66, elevation: 570 }), saved, "dark"), {
    position: { latitude: -33.45, longitude: -70.66, elevation: 570 },
    near: null,
  });
});
