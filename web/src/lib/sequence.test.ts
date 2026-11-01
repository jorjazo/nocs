import assert from "node:assert/strict";
import { test } from "node:test";
import { isActive, newTemplate, nextFilter, sequenceId } from "./sequence.ts";

test("a target's sequence id is a file name", () => {
  assert.equal(sequenceId("NGC 253"), "ngc-253");
  assert.equal(sequenceId("Nebulosa de Carina (η Car)"), "nebulosa-de-carina-car");
  assert.equal(sequenceId("Gran Nube de Magallanes"), "gran-nube-de-magallanes");
  assert.equal(sequenceId("Ñandú"), "nandu");
  assert.equal(sequenceId("***"), "sequence");
  assert.ok(/^[a-z0-9][a-z0-9-]{0,63}$/.test(sequenceId("x".repeat(100))));
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
