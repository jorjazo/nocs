import assert from "node:assert/strict";
import { test } from "node:test";
import { pageWidth } from "./layout.ts";

test("the Session and Rig tabs get the wide page", () => {
  assert.equal(pageWidth({ screen: "session" }), "wide");
  assert.equal(pageWidth({ screen: "rig" }), "wide");
  assert.equal(pageWidth({ screen: "rig", section: "site" }), "wide");
});

test("Explore, Sequences, Plan and Visitors are edge to edge", () => {
  assert.equal(pageWidth({ screen: "explore" }), "full");
  assert.equal(pageWidth({ screen: "sequence" }), "full");
  assert.equal(pageWidth({ screen: "plan" }), "full");
  assert.equal(pageWidth({ screen: "visits" }), "full");
});

test("every other screen keeps one readable column", () => {
  for (const route of [
    { screen: "tonight" },
    { screen: "plan-edit" },
    { screen: "plan-add" },
    { screen: "plan-target", id: "m42" },
    { screen: "sequence-edit" },
    { screen: "report", id: 3 },
    { screen: "target", id: "M42" },
    { screen: "profile", id: null },
    { screen: "site", id: "home" },
    { screen: "dev" },
  ] as const) {
    assert.equal(pageWidth(route), "narrow", route.screen);
  }
});
