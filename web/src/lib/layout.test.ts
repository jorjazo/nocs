import assert from "node:assert/strict";
import { test } from "node:test";
import { pageWidth } from "./layout.ts";

test("the Session tab gets the wide page", () => {
  assert.equal(pageWidth({ screen: "session" }), "wide");
});

test("Live view is edge to edge", () => {
  assert.equal(pageWidth({ screen: "live" }), "full");
});

test("every other screen keeps one readable column", () => {
  for (const route of [
    { screen: "tonight" },
    { screen: "plan" },
    { screen: "rig" },
    { screen: "sequence" },
    { screen: "report", id: 3 },
    { screen: "target", id: "M42" },
    { screen: "profile", id: null },
    { screen: "site", id: "home" },
    { screen: "dev" },
  ] as const) {
    assert.equal(pageWidth(route), "narrow", route.screen);
  }
});
