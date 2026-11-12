import assert from "node:assert/strict";
import { test } from "node:test";
import {
  currentRow,
  focusReason,
  frameLabel,
  frameName,
  isActive,
  newTemplate,
  nextFilter,
  runProgress,
  sequenceId,
  triggerDue,
} from "./sequence.ts";

test("a target's sequence id is a file name", () => {
  assert.equal(sequenceId("NGC 253"), "ngc-253");
  assert.equal(sequenceId("Nebulosa de Carina (η Car)"), "nebulosa-de-carina-car");
  assert.equal(sequenceId("Gran Nube de Magallanes"), "gran-nube-de-magallanes");
  assert.equal(sequenceId("Ñandú"), "nandu");
  assert.equal(sequenceId("***"), "sequence");
  assert.ok(/^[a-z0-9][a-z0-9-]{0,63}$/.test(sequenceId("x".repeat(100))));
});

test("frames are named after a catalog target's label", () => {
  const m42 = { id: "M 42", name: "M 42 · Gran Nebulosa de Orión", ra: 5.59, dec: -5.39 };
  assert.equal(frameName(m42), "M 42");
  assert.equal(newTemplate(m42, null, false).target.name, "M 42");
  assert.equal(newTemplate(m42, null, false).name, "M 42 · Gran Nebulosa de Orión");
  assert.equal(frameName({ name: "My field · east", ra: 1, dec: 2 }), "My field · east");
});

test("a new row takes the first filter no row uses", () => {
  const rows = [{ filter: "L", exposure: 120, count: 20 }];
  assert.equal(nextFilter(rows, ["L", "R", "G", "B"]), "R");
  assert.equal(nextFilter([...rows, { filter: "R", exposure: 1, count: 1 }], ["L", "R"]), "L");
  assert.equal(nextFilter(rows, []), null);
});

test("a new template images the target from dusk to dawn", () => {
  const template = newTemplate({ name: "NGC 253", ra: 0.79, dec: -25.29 }, "L", false);
  assert.deepEqual(template.target, { name: "NGC 253", ra: 0.79, dec: -25.29 });
  assert.equal(template.rows[0].filter, "L");
  assert.equal(template.start_at_dusk, true);
  assert.equal(isActive(null), false);
});

test("a new template's row keeps the camera's gain and offset", () => {
  const target = { name: "NGC 253", ra: 0.79, dec: -25.29 };
  const [row] = newTemplate(target, "L", false, true, { gain: 100, offset: 50 }).rows;
  assert.equal(row.gain, 100);
  assert.equal(row.offset, 50);
  // Without a camera, the row says "the camera's" (null) until edited.
  const [blank] = newTemplate(target, "L", false).rows;
  assert.equal(blank.gain, null);
  assert.equal(blank.offset, null);
});

test("a run's progress adds its rows up", () => {
  const run = {
    run: "r",
    name: "NGC 253",
    state: "running" as const,
    started: "2026-11-01T01:00:00+00:00",
    restarts: 0,
    current: "targets.0.1.3",
    plans: {
      "targets.0.1.3": {
        target: "NGC 253",
        rows: [
          { filter: "L", exposure: 120, count: 10, done: 10 },
          { filter: "R", exposure: 60, count: 5, done: 2 },
        ],
      },
    },
    outcome: null,
    error: null,
  };
  const progress = runProgress(run);
  assert.equal(progress.done, 12);
  assert.equal(progress.total, 15);
  assert.equal(progress.left, 3 * 63);
  assert.equal(currentRow(run, "L")?.filter, "R");
  assert.equal(currentRow(run, "R")?.done, 2);
  assert.equal(currentRow({ ...run, current: "end.0" }, "R"), null);
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
