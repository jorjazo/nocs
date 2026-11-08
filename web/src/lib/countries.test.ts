import assert from "node:assert/strict";
import { test } from "node:test";
import { COUNTRIES, countryChoices, isCountry } from "./countries.ts";

test("countries are named in the app's language and sorted by name", () => {
  const choices = countryChoices("es");
  assert.equal(choices.length, COUNTRIES.length);
  assert.deepEqual(
    choices.find((c) => c.code === "DE"),
    { code: "DE", name: "Alemania" },
  );
  const names = choices.map((c) => c.name);
  assert.deepEqual(names, [...names].sort((a, b) => a.localeCompare(b, "es")));
});

test("only the radio's countries are countries", () => {
  assert.ok(isCountry("CL"));
  for (const code of ["419", "cl", "XX", "EU", "00", ""]) assert.ok(!isCountry(code), code);
});
