import assert from "node:assert/strict";
import { test } from "node:test";
import { folderName } from "./storage.ts";

test("folder names are cleaned as the server does", () => {
  assert.equal(folderName("M 31"), "M_31");
  assert.equal(folderName("  NGC 7000:  North America?  "), "NGC_7000_North_America");
  assert.equal(folderName("Nebulosa de Carina"), "Nebulosa_de_Carina");
  assert.equal(folderName("η Carinae"), "η_Carinae");
  assert.equal(folderName("..."), "");
});
