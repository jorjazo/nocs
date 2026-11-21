import assert from "node:assert/strict";
import { test } from "node:test";
import {
  copyDone,
  lineDone,
  moved,
  newId,
  newLine,
  parseDec,
  parseRa,
  planIds,
  planShape,
  targetDone,
  targetLeft,
  targetSeconds,
} from "./plan.ts";
import type { NightPlan, PlanTarget } from "./types.ts";

const M42: PlanTarget = {
  id: "m42",
  name: "M 42",
  object: "NGC 1976",
  ra: 5.588,
  dec: -5.39,
  lines: [
    { id: "a", filter: "L", exposure: 60, count: 10, done: 4 },
    { id: "b", filter: "R", exposure: 120, count: 5, done: 7 },
  ],
};

test("ids are new to the plan", () => {
  const plan: NightPlan = { targets: [M42] };
  assert.deepEqual(planIds(plan), ["m42", "a", "b"]);
  let n = 0;
  const id = newId(["00000000"], () => [0, 0.5][n++] ?? 0.5);
  assert.ok(id !== "00000000");
  assert.ok(/^[a-z0-9]{8}$/.test(id));
});

test("a new line takes the next filter, and the last line's settings", () => {
  const line = newLine(M42.lines ?? [], ["L", "R", "G"], "c");
  assert.deepEqual(line, { id: "c", filter: "G", exposure: 120, count: 5, gain: null, offset: null, done: 0 });
  assert.equal(newLine([], [], "d", { gain: 100, offset: 10 }).filter, null);
  assert.equal(newLine([], ["L"], "d", { gain: 100, offset: 10 }).gain, 100);
});

test("what a target has and still needs", () => {
  assert.equal(targetLeft(M42), 6);
  assert.equal(targetDone(M42), 9);
  assert.equal(targetSeconds(M42), 6 * 63);
});

test("targets move up and down", () => {
  assert.deepEqual(moved(["a", "b", "c"], 2, -1), ["a", "c", "b"]);
  assert.deepEqual(moved(["a", "b", "c"], 0, -1), ["a", "b", "c"]);
});

test("the server's counts are not changes, and come into a draft by id", () => {
  const live: NightPlan = { targets: [structuredClone(M42)] };
  const draft: NightPlan = structuredClone(live);
  const line = draft.targets?.[0]?.lines?.[0];
  (live.targets?.[0]?.lines ?? [])[0]!.done = 5;
  assert.equal(planShape(draft), planShape(live));
  copyDone(draft, live);
  assert.equal(line?.done, 5);
  assert.equal(lineDone(live, "a"), 5);
  assert.equal(lineDone(null, "a"), 0);
  (draft.targets?.[0]?.lines ?? [])[0]!.count = 20;
  assert.ok(planShape(draft) !== planShape(live));
});

test("coordinates as typed", () => {
  assert.equal(parseRa("5.588"), 5.588);
  assert.ok(Math.abs((parseRa("05 35 17") ?? 0) - 5.58806) < 1e-4);
  assert.ok(Math.abs((parseRa("5h35m17s") ?? 0) - 5.58806) < 1e-4);
  assert.equal(parseRa("24"), null);
  assert.equal(parseRa("-1"), null);
  assert.equal(parseRa("5 61"), null);
  assert.equal(parseRa("nope"), null);
  assert.ok(Math.abs((parseDec("-05:23:28") ?? 0) + 5.39111) < 1e-4);
  assert.ok(Math.abs((parseDec("-5°23′28″") ?? 0) + 5.39111) < 1e-4);
  assert.equal(parseDec("-5,39"), -5.39);
  assert.equal(parseDec("91"), null);
  assert.equal(parseDec(""), null);
});
