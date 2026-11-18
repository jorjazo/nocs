import assert from "node:assert/strict";
import { test } from "node:test";
import {
  currentPlan,
  currentRow,
  fitGroup,
  focusReason,
  frameLabel,
  freeId,
  isActive,
  newGroup,
  newTemplate,
  nextFilter,
  prompts,
  runProgress,
  sequenceId,
  triggerDue,
  workingView,
} from "./sequence.ts";
import type { SequenceRun } from "./types.ts";

test("a sequence's id is a file name, and a new one is free", () => {
  assert.equal(sequenceId("NGC 253"), "ngc-253");
  assert.equal(sequenceId("Nebulosa de Carina (η Car)"), "nebulosa-de-carina-car");
  assert.equal(sequenceId("Ñandú"), "nandu");
  assert.equal(sequenceId("***"), "sequence");
  assert.ok(/^[a-z0-9][a-z0-9-]{0,63}$/.test(sequenceId("x".repeat(100))));
  assert.equal(freeId("Sequence", []), "sequence");
  assert.equal(freeId("Sequence", ["sequence", "sequence-2"]), "sequence-3");
});

test("a new template takes lights from dusk to dawn, with the camera's settings", () => {
  const template = newTemplate("M 42", "L", false, true, { gain: 100, offset: 50 });
  assert.equal(template.name, "M 42");
  assert.deepEqual(template.groups[0], { frame_type: "light", filter: "L", exposure: 120, count: 20, gain: 100, offset: 50 });
  assert.equal(template.start_at_dusk, true);
  assert.equal(template.cooling, "off");
  assert.equal(template.center, true);
  assert.equal(isActive(null), false);
  // Without a camera, the group says "the camera's" (null) until edited.
  assert.equal(newTemplate("x", "L", false).groups[0]?.gain, null);
});

test("a new group follows the last one", () => {
  const groups = [{ frame_type: "light" as const, filter: "L", exposure: 120, count: 20 }];
  assert.equal(newGroup(groups, ["L", "R", "G", "B"]).filter, "R");
  assert.equal(nextFilter([...groups, { filter: "R", exposure: 1, count: 1 }], ["L", "R"]), "L");
  assert.equal(nextFilter(groups, []), null);
  const dark = newGroup([...groups, { frame_type: "dark", exposure: 300, count: 10 }], ["L"]);
  assert.deepEqual([dark.frame_type, dark.exposure, dark.count], ["dark", 300, 10]);
});

test("a group fits its kind", () => {
  assert.deepEqual(fitGroup({ frame_type: "bias", filter: "L", exposure: 3, count: 5 }), {
    frame_type: "bias",
    filter: null,
    exposure: null,
    count: 5,
  });
  assert.equal(fitGroup({ frame_type: "dark", filter: "L", count: 5 }).exposure, 120);
  assert.equal(fitGroup({ frame_type: "flat", filter: "L", count: 5 }).filter, "L");
});

test("the run asks for the rig each time the kind of frames changes", () => {
  const light = { frame_type: "light" as const, exposure: 1, count: 1 };
  const flat = { frame_type: "flat" as const, count: 1 };
  const bias = { frame_type: "bias" as const, count: 1 };
  const dark = { frame_type: "dark" as const, exposure: 1, count: 1 };
  assert.deepEqual(prompts([light, light, flat, bias, dark]), ["flat", "dark"]);
  assert.deepEqual(prompts([dark, light]), ["dark", "light"]);
  assert.deepEqual(prompts([light]), []);
});

const run: SequenceRun = {
  run: "r",
  sequence: "m42",
  name: "M 42",
  state: "running",
  started: "2026-11-01T01:00:00+00:00",
  restarts: 0,
  current: "targets.0.3.2",
  plans: {
    "targets.0.3.2": {
      target: "M 42",
      frame_type: "light",
      rows: [
        { filter: "L", exposure: 120, count: 10, done: 10 },
        { filter: "R", exposure: 60, count: 5, done: 2 },
      ],
    },
    "targets.1.1": { target: "M 42", frame_type: "bias", rows: [{ filter: null, exposure: null, count: 10, done: 0 }] },
  },
  outcome: null,
  error: null,
  prompt: null,
};

test("a run's progress adds its groups up", () => {
  const progress = runProgress(run);
  assert.equal(progress.done, 12);
  assert.equal(progress.total, 25);
  assert.equal(progress.left, 3 * 63 + 10 * 3.001);
  assert.deepEqual(
    progress.rows.map((r) => r.frameType),
    ["light", "light", "bias"],
  );
  assert.equal(currentRow(run, "L")?.filter, "R");
  assert.equal(currentRow(run, "R")?.done, 2);
  assert.equal(currentRow({ ...run, current: "end.0" }, "R"), null);
  assert.equal(currentPlan({ ...run, current: "targets.1.0" }), null);
  assert.equal(currentPlan({ ...run, current: "targets.0.3" }), "targets.0.3.2");
});

test("Explore and Sequences exclude each other", () => {
  assert.equal(workingView(run, {}), "sequence");
  assert.equal(workingView({ ...run, state: "finished" }, { a: { kind: "loop", state: "running" } }), "explore");
  assert.equal(workingView(null, { a: { kind: "loop", state: "succeeded" }, b: { kind: "autofocus", state: "running" } }), null);
});

test("a trigger event names the trigger that fired", () => {
  assert.deepEqual(triggerDue("autofocus: temperature -1.2 °C"), { kind: "autofocus", reason: "temperature -1.2 °C" });
  // Not an autofocus: the Session tab once read "Autofocus due: dither: 3 frames".
  assert.deepEqual(triggerDue("dither: 3 frames"), { kind: "dither", frames: 3 });
  assert.deepEqual(triggerDue("recenter: 10 frames"), { kind: "recenter", frames: 10 });
  assert.deepEqual(triggerDue("flip: waiting 4.5 min for the meridian"), { kind: "flip", waiting: 4.5 });
  assert.deepEqual(triggerDue("flip: +5.2 min past the meridian"), { kind: "flip", waiting: null });
  assert.deepEqual(triggerDue("something new"), { kind: "other", message: "something new" });
});

test("an autofocus trigger's reason is told apart", () => {
  assert.deepEqual(focusReason("filter Ha"), { why: "filter", filter: "Ha" });
  assert.deepEqual(focusReason("temperature -1.2 °C"), { why: "temperature", change: -1.2 });
  assert.deepEqual(focusReason("temperature +0.8 °C"), { why: "temperature", change: 0.8 });
  assert.deepEqual(focusReason("45 min"), { why: "minutes", minutes: 45 });
  assert.deepEqual(focusReason("3 frames"), { why: "frames", frames: 3 });
  assert.deepEqual(focusReason("HFR +12%"), { why: "hfr", percent: 12 });
  assert.deepEqual(focusReason("something new"), { why: "other", text: "something new" });
});

test("a frame's label names its filter, or only its number without one", () => {
  assert.equal(frameLabel({ filter: "R", done: 11, count: 15 }), "R 11");
  assert.equal(frameLabel({ filter: null, done: 5, count: 20 }), "#5");
  assert.equal(frameLabel({ filter: "", done: 5 }), "#5");
  assert.equal(frameLabel({ filter: "L" }), "L");
});
