import assert from "node:assert/strict";
import { test } from "node:test";
import { choiceFor, choiceKey, driverChoices, driverOptions, matches, type DriverChoice } from "./drivers.ts";
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

test("the role's groups first, then the others; model or maker matches before driver ones", () => {
  const choices = driverChoices([
    entry("indi_simulator_telescope", "Telescope Simulator", "Simulator"),
    entry("indi_lx200am5", "ZWO AM5", "ZWO"),
    entry("indi_lx200generic", "LX200 Classic", "Meade"),
    entry("indi_lx200generic", "LX200 GPS", "Meade"),
    entry("indi_simulator_ccd", "CCD Simulator", "Simulator", "CCDs"),
    entry("indi_simulator_focus", "Focuser Simulator", "Simulator", "Focusers"),
  ]);
  const listed = (wanted: string[], query: string, current: DriverChoice | null = null) =>
    driverOptions(choices, wanted, query, current).map((g) => [g.group, g.choices.map((c) => c.text)]);

  assert.deepEqual(listed(["Telescopes"], "sim"), [
    ["Telescopes", ["Telescope Simulator"]],
    [null, ["CCD Simulator", "Focuser Simulator"]],
  ]);
  assert.deepEqual(listed(["Focusers", "Telescopes"], "sim"), [
    ["Focusers", ["Focuser Simulator"]],
    ["Telescopes", ["Telescope Simulator"]],
    [null, ["CCD Simulator"]],
  ]);
  // "lx200" names two Meade models and only the AM5's driver: the models first.
  assert.deepEqual(listed(["Telescopes"], "lx200"), [["Telescopes", ["LX200 Classic", "LX200 GPS", "ZWO AM5"]]]);
  assert.deepEqual(listed(["CCDs"], "nothing"), []);
  // Nothing typed: everything, groups without a match left out.
  assert.deepEqual(listed(["Weather"], "").map(([group]) => group), [null]);
});

test("a driver installed by hand is offered first among the others", () => {
  const choices = driverChoices(CATALOG);
  const byHand = choiceFor(choices, "indi_my_mount", null);
  const groups = driverOptions(choices, ["Telescopes"], "", byHand);
  assert.deepEqual(groups.at(-1)?.choices[0]?.text, "indi_my_mount");
  assert.deepEqual(
    driverOptions(choices, ["Telescopes"], "my mount", byHand).map((g) => g.choices.map((c) => c.text)),
    [["indi_my_mount"]],
  );
  // One from the catalog is not repeated.
  const am5 = choiceFor(choices, "indi_lx200am5", "ZWO AM5");
  const all = driverOptions(choices, ["Telescopes"], "", am5).flatMap((g) => g.choices);
  assert.equal(all.filter((c) => c.text === "ZWO AM5").length, 1);
});
