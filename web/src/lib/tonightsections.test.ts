import assert from "node:assert/strict";
import { test } from "node:test";
import { arrange, isOpen } from "./tonightsections.ts";

test("the night starts open, the rest closed, and the browser's choice wins", () => {
  assert.equal(isOpen({}, "night"), true);
  assert.equal(isOpen({}, "weather"), false);
  assert.equal(isOpen({ night: false, weather: true }, "night"), false);
  assert.equal(isOpen({ night: false, weather: true }, "weather"), true);
});

test("the checklist goes first while something is left, last once done", () => {
  assert.equal(arrange(false)[0], "preparation");
  assert.equal(arrange(true).at(-1), "preparation");
  assert.equal(arrange(true).length, arrange(false).length);
  assert.equal(new Set(arrange(true)).size, arrange(true).length);
});
