import assert from "node:assert/strict";
import { test } from "node:test";
import { applies, blockerText, blockersOf, fixFor, fixRoute, statuses } from "./checklist.ts";
import { en } from "./i18n/en.ts";
import { es } from "./i18n/es.ts";
import type { PreparationBlocker, PreparationState, PreparationStep } from "./types.ts";

function step(applies: boolean, ...blockers: Partial<PreparationBlocker>[]): PreparationStep {
  return {
    applies,
    blockers: blockers.map((b) => ({ reason: "not_connected", role: null, message: "", ...b })),
  };
}

function preparation(changes: Partial<PreparationState> = {}): PreparationState {
  const ready = step(true);
  return { polar_align: ready, focus: ready, frame: ready, guide: ready, ...changes };
}

test("the first step that can run is next, later ones are ready", () => {
  assert.deepEqual(
    statuses([
      { done: true, blocked: false },
      { done: false, blocked: false },
      { done: false, blocked: false },
    ]),
    ["done", "next", "ready"],
  );
});

test("a blocked step is never next: the next one that can run is", () => {
  // rc4's night: connected, polar alignment blocked by the site; focus is next.
  assert.deepEqual(
    statuses([
      { done: true, blocked: false },
      { done: false, blocked: true },
      { done: false, blocked: false },
      { done: false, blocked: true },
    ]),
    ["done", "blocked", "next", "blocked"],
  );
});

test("a done step stays done even if it could not run now", () => {
  assert.deepEqual(statuses([{ done: true, blocked: true }]), ["done"]);
});

test("with everything blocked nothing is next", () => {
  assert.deepEqual(
    statuses([
      { done: false, blocked: true },
      { done: false, blocked: true },
    ]),
    ["blocked", "blocked"],
  );
});

test("the steps come from the server's state", () => {
  const p = preparation({ guide: step(false), polar_align: step(true, { reason: "no_site" }) });
  assert.equal(applies(p, "guide"), false);
  assert.equal(applies(p, "polar"), true);
  assert.equal(applies(null, "polar"), false);
  assert.deepEqual(blockersOf(p, "polar", 0), [{ reason: "no_site", role: null, fix: "addSite" }]);
  assert.deepEqual(blockersOf(p, "focus", 0), []);
  assert.deepEqual(blockersOf(undefined, "focus", 0), []);
});

test("each blocker says where it is fixed", () => {
  assert.equal(fixFor({ reason: "no_site", role: null }, 0), "addSite");
  assert.equal(fixFor({ reason: "no_site", role: null }, 2), "chooseSite");
  // Before connecting, the Connect step above is the fix.
  assert.equal(fixFor({ reason: "not_connected", role: null }, 0), null);
  assert.equal(fixFor({ reason: "not_connected", role: "mount" }, 0), "rig");
  assert.equal(fixFor({ reason: "parked", role: null }, 0), "rig");
  assert.equal(fixFor({ reason: "no_phd2", role: null }, 0), "guiding");
  assert.equal(fixFor({ reason: "no_solver", role: null }, 0), null);
  assert.equal(fixFor({ reason: "no_database", role: null }, 0), null);
  assert.deepEqual(fixRoute("addSite"), { screen: "site", id: null });
  assert.deepEqual(fixRoute("chooseSite"), { screen: "rig" });
  assert.deepEqual(fixRoute("guiding"), { screen: "guiding" });
});

test("a blocker reads as what is missing", () => {
  assert.equal(blockerText(en, { reason: "no_site", role: null }), "Needs the site; a rough one is enough.");
  assert.equal(blockerText(en, { reason: "not_connected", role: null }), "Connect first.");
  assert.equal(blockerText(en, { reason: "not_connected", role: "mount" }), "Mount is not ready.");
  assert.equal(blockerText(es, { reason: "not_connected", role: "mount" }), "Montura: todavía no está disponible.");
});
