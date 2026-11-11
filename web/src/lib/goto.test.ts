import assert from "node:assert/strict";
import { test } from "node:test";
import { goRefusal } from "./goto.ts";

test("refusals the app offers a way past", () => {
  assert.equal(goRefusal(409, "the target is 12.0° below the horizon"), "horizon");
  assert.equal(goRefusal(409, "mount is busy (guiding)"), "guiding");
  // A job moving the mount is waited for, not stopped.
  assert.equal(goRefusal(409, "mount is busy (goto 3f2a)"), null);
  assert.equal(goRefusal(503, "the mount is not connected"), null);
});
