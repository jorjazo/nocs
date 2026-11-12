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

function words(query: string): string[] {
  return fold(query).split(/\s+/).filter(Boolean);
}

function contains(text: string, query: string): boolean {
  const haystack = fold(text);
  return words(query).every((word) => haystack.includes(word));
}

// Every word of the query in the model, its manufacturer or the driver's executable.
export function matches(choice: DriverChoice, query: string): boolean {
  return contains(`${choice.text} ${choice.manufacturer} ${choice.driver}`, query);
}

// A group of the driver list: one of the catalog's, or null for every other driver.
export type DriverGroup = { group: string | null; choices: DriverChoice[] };

// What the profile editor offers for a role: the role's own catalog groups first, in
// their order, then every other driver. Within each, choices whose model or maker
// match the query come before those that match only by executable (`lx200` finds
// the ZWO AM5), then by name. A current choice the catalog lacks (a driver
// installed by hand) is offered first among the others.
export function driverOptions(
  choices: readonly DriverChoice[],
  wanted: readonly string[],
  query: string,
  current: DriverChoice | null,
): DriverGroup[] {
  const extra = current && !choices.some((c) => c.key === current.key) ? [current] : [];
  const shown = [...extra, ...choices].filter((c) => matches(c, query));
  const byName = (c: DriverChoice) => (contains(`${c.text} ${c.manufacturer}`, query) ? 0 : 1);
  const ranked = shown
    .map((choice, index) => ({ choice, rank: byName(choice), index }))
    .sort((a, b) => a.rank - b.rank || a.index - b.index)
    .map(({ choice }) => choice);
  const groups: DriverGroup[] = wanted.map((group) => ({ group, choices: ranked.filter((c) => c.group === group) }));
  groups.push({ group: null, choices: ranked.filter((c) => !wanted.includes(c.group)) });
  return groups.filter((g) => g.choices.length > 0);
}
