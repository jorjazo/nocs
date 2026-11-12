import assert from "node:assert/strict";
import { test } from "node:test";
import { en } from "./en.ts";
import { es } from "./es.ts";

test("the frame in progress names its filter, and leaves it out without one", () => {
  assert.equal(en.session.exposing("R", 5, 20), "Exposing R · frame 5 of 20");
  assert.equal(en.session.exposing(null, 5, 20), "Exposing frame 5 of 20");
  assert.equal(es.session.exposing("R", 5, 20), "Exponiendo R · toma 5 de 20");
  assert.equal(es.session.exposing(null, 5, 20), "Exponiendo la toma 5 de 20");
});

test("an autofocus that is due says why in the reader's words", () => {
  const r = en.session.event.focusReason;
  assert.equal(en.session.event.focusDue(r.frames(3)), "Autofocus due: 3 frames since the last");
  assert.equal(r.filter("Ha"), "the filter changed to Ha");
  assert.equal(es.session.event.focusDue(es.session.event.focusReason.frames(1)), "Toca enfocar: 1 toma desde el último enfoque");
});
