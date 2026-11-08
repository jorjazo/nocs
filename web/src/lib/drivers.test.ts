import assert from "node:assert/strict";
import { test } from "node:test";
import { choiceFor, choiceKey, driverChoices, matches } from "./drivers.ts";
import type { Driver } from "./types.ts";

function entry(driver: string, label: string, manufacturer = "", group = "Telescopes"): Driver {
  return { driver, name: driver, label, manufacturer, group };
}

const CATALOG = [
  entry("indi_ioptronv3_telescope", "iOptron GEM45", "iOptron"),
  entry("indi_ioptronv3_telescope", "iOptron CEM40", "iOptron"),
  entry("indi_lx200am5", "ZWO AM5", "ZWO"),
  entry("indi_lx200am5", "ZWO AM5", "ZWO"), // listed twice by two catalog files
  entry("indi_mi_ccd_usb", "MI CCD", "Moravian", "CCDs"),
  entry("indi_mi_ccd_eth", "MI CCD", "Moravian", "CCDs"),
];

test("one choice per model, named by the model", () => {
  assert.deepEqual(
    driverChoices(CATALOG).map((c) => c.text),
    ["iOptron CEM40", "iOptron GEM45", "MI CCD (indi_mi_ccd_eth)", "MI CCD (indi_mi_ccd_usb)", "ZWO AM5"],
  );
});

test("a saved device finds its model, else its driver's first one", () => {
  const choices = driverChoices(CATALOG);
  assert.equal(choiceFor(choices, "indi_ioptronv3_telescope", "iOptron GEM45")?.text, "iOptron GEM45");
  assert.equal(choiceFor(choices, "indi_ioptronv3_telescope", null)?.text, "iOptron CEM40");
  assert.equal(choiceFor(choices, "indi_ioptronv3_telescope", "iOptron CEM120")?.text, "iOptron CEM40");
  const byHand = choiceFor(choices, "indi_my_mount", null);
  assert.deepEqual([byHand?.key, byHand?.text], [choiceKey("indi_my_mount", null), "indi_my_mount"]);
  assert.equal(choiceFor(choices, "", null), null);
});

test("the filter matches every word in the model, manufacturer or driver", () => {
  const choices = driverChoices(CATALOG);
  const pick = (text: string) => {
    const choice = choices.find((c) => c.text === text);
    assert.ok(choice);
    return choice;
  };
  const [cem40, gem45, usb, am5] = [
    pick("iOptron CEM40"),
    pick("iOptron GEM45"),
    pick("MI CCD (indi_mi_ccd_usb)"),
    pick("ZWO AM5"),
  ];
  assert.ok(matches(gem45, "gem45"));
  assert.ok(matches(gem45, "  iOPTRON  gem "));
  assert.ok(!matches(cem40, "gem45"));
  assert.ok(matches(usb, "moravian usb"));
  assert.ok(matches(am5, "lx200"));
  assert.ok(matches(am5, ""));
});
