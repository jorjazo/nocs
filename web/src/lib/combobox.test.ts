import assert from "node:assert/strict";
import { test } from "node:test";
import { moveActive } from "./combobox.ts";

test("arrows move through the options and wrap around", () => {
  assert.equal(moveActive("ArrowDown", -1, 3), 0);
  assert.equal(moveActive("ArrowDown", 0, 3), 1);
  assert.equal(moveActive("ArrowDown", 2, 3), 0);
  assert.equal(moveActive("ArrowUp", -1, 3), 2);
  assert.equal(moveActive("ArrowUp", 0, 3), 2);
  assert.equal(moveActive("ArrowUp", 2, 3), 1);
});

test("pages jump ten options and stop at the ends", () => {
  assert.equal(moveActive("PageDown", -1, 30), 10);
  assert.equal(moveActive("PageDown", 25, 30), 29);
  assert.equal(moveActive("PageUp", 15, 30), 5);
  assert.equal(moveActive("PageUp", 3, 30), 0);
});

test("other keys, or no options, leave the list alone", () => {
  assert.equal(moveActive("Home", 3, 30), null);
  assert.equal(moveActive("a", 3, 30), null);
  assert.equal(moveActive("ArrowDown", -1, 0), null);
});
