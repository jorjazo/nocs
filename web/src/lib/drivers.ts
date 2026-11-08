// Driver choices for the profile editor: one per model of the rig's INDI catalog,
// named by the model (one driver serves many: iOptronV3 every iOptron mount).
import type { Driver } from "./types";

export type DriverChoice = {
  key: string;
  driver: string;
  model: string | null;
  text: string;
  group: string;
  manufacturer: string;
};

export function choiceKey(driver: string, model: string | null): string {
  return `${driver}\n${model ?? ""}`;
}

export function driverChoices(catalog: readonly Driver[]): DriverChoice[] {
  const byKey = new Map<string, DriverChoice>();
  for (const entry of catalog) {
    const key = choiceKey(entry.driver, entry.label);
    if (!byKey.has(key)) {
      byKey.set(key, {
        key,
        driver: entry.driver,
        model: entry.label,
        text: entry.label,
        group: entry.group,
        manufacturer: entry.manufacturer,
      });
    }
  }
  const choices = [...byKey.values()];
  // One model name from two drivers (MI CCD over USB and over Ethernet): say which.
  const drivers = new Map<string, Set<string>>();
  for (const choice of choices) drivers.set(choice.text, (drivers.get(choice.text) ?? new Set()).add(choice.driver));
  for (const choice of choices) {
    if ((drivers.get(choice.text)?.size ?? 0) > 1) choice.text = `${choice.text} (${choice.driver})`;
  }
  return choices.sort((a, b) => a.text.localeCompare(b.text));
}

// What a saved device stands for: its model while the catalog has it, else the
// driver's first model; a driver missing from the catalog (installed by hand)
// stands for itself.
export function choiceFor(choices: readonly DriverChoice[], driver: string, model: string | null): DriverChoice | null {
  if (!driver) return null;
  return (
    choices.find((c) => c.driver === driver && c.model === model) ??
    choices.find((c) => c.driver === driver) ?? {
      key: choiceKey(driver, null),
      driver,
      model: null,
      text: driver,
      group: "",
      manufacturer: "",
    }
  );
}

function fold(text: string): string {
  return text.normalize("NFD").replace(/\p{M}/gu, "").toLowerCase();
}

// Every word of the query in the model, its manufacturer or the driver's executable.
export function matches(choice: DriverChoice, query: string): boolean {
  const haystack = fold(`${choice.text} ${choice.manufacturer} ${choice.driver}`);
  return fold(query)
    .split(/\s+/)
    .filter(Boolean)
    .every((word) => haystack.includes(word));
}
