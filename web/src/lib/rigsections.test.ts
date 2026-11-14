import assert from "node:assert/strict";
import { test } from "node:test";
import {
  devicesAttention,
  isOpen,
  isRigSection,
  networkAttention,
  parseOpen,
  rigAttention,
  siteAttention,
  storageAttention,
  systemAttention,
  updatesWorthIt,
} from "./rigsections.ts";
import type {
  AppState,
  EquipmentState,
  IndiServer,
  NetworkState,
  SitesState,
  StorageState,
  SystemState,
  UpdatesState,
  UpgradablePackage,
} from "./types.ts";

const server: IndiServer = { connected: true, error: null, host: "localhost", port: 7624, responsive: true };

function equipment(connection: EquipmentState["connection"], ...statuses: string[]): EquipmentState {
  const roles = ["mount", "main_camera", "focuser"];
  return {
    active: "sim",
    connection,
    error: null,
    profiles: {},
    devices: Object.fromEntries(
      statuses.map((status, i) => [
        roles[i]!,
        { driver: "indi_x", device: "X", status, error: null, unresponsive_since: null },
      ]),
    ),
  } as EquipmentState;
}

const storage: StorageState = {
  choice: "auto",
  destination: "internal",
  destinations: [],
  error: null,
  target: null,
  template: "",
  unmounted: [],
};

function system(warnings: string[] = []): SystemState {
  return {
    error: null,
    helper: true,
    hostname: "nocs",
    operations: [],
    health: { warnings, cpu_temperature: 40 } as unknown as SystemState["health"],
  };
}

function updates(packages: Partial<UpgradablePackage>[], reboot_required = false): UpdatesState {
  return {
    checked: null,
    error: null,
    installed: "0.1.0",
    log: [],
    packages: packages.map((p) => ({ name: "x", from: "1", to: "2", kind: "system", security: false, reboot: false, ...p })),
    previous: null,
    reboot_required,
    state: "idle",
    task: null,
    upgraded: [],
  } as UpdatesState;
}

test("only known sections are sections", () => {
  assert.ok(isRigSection("site"));
  assert.ok(!isRigSection("profile"));
});

test("devices start open, the rest closed, until the browser says otherwise", () => {
  assert.equal(isOpen({}, "devices"), true);
  assert.equal(isOpen({}, "updates"), false);
  assert.equal(isOpen({ devices: false, updates: true }, "devices"), false);
  assert.equal(isOpen({ devices: false, updates: true }, "updates"), true);
});

test("whatever the browser kept, the screen still opens", () => {
  assert.deepEqual(parseOpen(null), {});
  assert.deepEqual(parseOpen("not json"), {});
  assert.deepEqual(parseOpen("[1, 2]"), {});
  assert.deepEqual(parseOpen('{"site": true, "storage": "yes"}'), { site: true });
});

test("devices: a disconnected rig with a working server needs nothing", () => {
  assert.equal(devicesAttention(equipment("disconnected", "disconnected"), server), null);
  assert.equal(devicesAttention(equipment("connected", "ready", "ready"), server), null);
});

test("devices: a device lost while connected, or the server, is a problem", () => {
  assert.equal(devicesAttention(equipment("connected", "ready", "disconnected"), server), "problem");
  assert.equal(devicesAttention(equipment("connected", "ready", "error"), server), "problem");
  assert.equal(devicesAttention(equipment("connected", "ready", "unresponsive"), server), "warning");
  assert.equal(devicesAttention(equipment("disconnected"), { ...server, responsive: false }), "problem");
  assert.equal(devicesAttention({ ...equipment("disconnected"), error: "boom" }, server), "problem");
});

test("storage: nowhere to save is a problem, a share that does not run a warning", () => {
  assert.equal(storageAttention(storage, null), null);
  assert.equal(storageAttention({ ...storage, destination: null }, null), "problem");
  assert.equal(storageAttention(storage, { on: true, running: false, clients: 0, shares: [] }), "warning");
});

test("system: a weak power supply is a problem, other warnings a warning", () => {
  assert.equal(systemAttention(system()), null);
  assert.equal(systemAttention(system(["hot"])), "warning");
  assert.equal(systemAttention(system(["hot", "under_voltage"])), "problem");
});

test("network: only the owner is told about the default password", () => {
  const network = { ap_default_password: true, last_join: null, joining: null } as unknown as NetworkState;
  assert.equal(networkAttention(network, true), "warning");
  assert.equal(networkAttention(network, false), null);
});

test("network: a failed join, kept until the next one, does not light the tab for good", () => {
  const failed = { ssid: "home", ok: false, error: "wrong password", at: "2026-11-14T10:00:00Z" };
  const network = { ap_default_password: false, last_join: failed, joining: null } as unknown as NetworkState;
  assert.equal(networkAttention(network, true), null);
});

test("site: no active site is a warning, no sites state is nothing", () => {
  assert.equal(siteAttention({ active: null, saved: {} } as unknown as SitesState), "warning");
  assert.equal(siteAttention({ active: "home", saved: {} } as unknown as SitesState), null);
  assert.equal(siteAttention(null), null);
});

test("updates: a new NOCS or security fixes are worth a dot, plain system updates are not", () => {
  assert.equal(updatesWorthIt(updates([{ kind: "system" }])), false);
  assert.equal(updatesWorthIt(updates([{ kind: "system", security: true }])), true);
  assert.equal(updatesWorthIt(updates([{ kind: "nocs", name: "nocs" }])), true);
  assert.equal(updatesWorthIt(updates([], true)), true);
});

test("the Rig tab: problems first, then updates, these for the owner only", () => {
  const app = { indi: { server }, storage, system: system(), updates: updates([{ kind: "nocs", name: "nocs" }]) } as AppState;
  assert.equal(rigAttention(app, true), "updates");
  assert.equal(rigAttention(app, false), null);
  assert.equal(rigAttention({ ...app, system: system(["memory"]) }, true), "warning");
  assert.equal(rigAttention({ ...app, storage: { ...storage, error: "full" } }, false), "problem");
  assert.equal(rigAttention({ ...app, sites: { active: null, saved: {} } as unknown as SitesState }, false), "warning");
});
