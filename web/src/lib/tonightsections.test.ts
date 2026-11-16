import assert from "node:assert/strict";
import { test } from "node:test";
import { arrange, isOpen, preparationOpen } from "./tonightsections.ts";

test("the night starts open, the rest closed, and the browser's choice wins", () => {
  assert.equal(isOpen({}, "night"), true);
  assert.equal(isOpen({}, "weather"), false);
  assert.equal(isOpen({ night: false, weather: true }, "night"), false);
  assert.equal(isOpen({ night: false, weather: true }, "weather"), true);
});

test("the checklist goes first while something is left, last once done", () => {
  const rest = ["night", "pointing", "weather", "actuators", "location", "host"];
  assert.deepEqual(arrange(false), ["preparation", ...rest]);
  assert.deepEqual(arrange(true), [...rest, "preparation"]);
});

test("the checklist is open while something is left, unless chosen by hand", () => {
  assert.equal(preparationOpen(false, null), true);
  assert.equal(preparationOpen(true, null), false);
  assert.equal(preparationOpen(false, false), false);
  assert.equal(preparationOpen(true, true), true);
});
