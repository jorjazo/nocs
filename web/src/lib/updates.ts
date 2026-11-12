// Box → Updates (ADR 0025): what apt would upgrade, as the owner decides on it.
// NOCS first, then the rig's own software (INDI, PHD2), then the rest of the
// system as a count with its security updates; every package in a list behind a
// disclosure.

import type { UpgradablePackage } from "./types.ts";

export type Kind = UpgradablePackage["kind"];
export type Component = "indi" | "phd2";

export interface ComponentUpdate {
  kind: Component;
  from: string;
  to: string;
  // Packages of it: INDI comes as several (indi-bin, libindi1, the drivers…).
  count: number;
}

export interface UpdateSummary {
  total: number;
  // The nocs package's update, if any (nocs-appliance's alone when only it has one).
  nocs: UpgradablePackage | null;
  components: ComponentUpdate[];
  system: { count: number; security: number };
  // A new kernel or firmware: the box runs it only after a restart.
  reboot: boolean;
  // Every package, by kind (NOCS, INDI, PHD2, system) and name.
  groups: { kind: Kind; packages: UpgradablePackage[] }[];
}

const ORDER: Kind[] = ["nocs", "indi", "phd2", "system"];
// The package whose version names the component, in order of preference.
const MAIN: Record<Component, string[]> = { indi: ["indi-bin", "libindi1"], phd2: ["phd2"] };

export function summarize(packages: UpgradablePackage[]): UpdateSummary {
  const byKind = (kind: Kind) =>
    packages.filter((p) => p.kind === kind).sort((a, b) => a.name.localeCompare(b.name));
  const groups = ORDER.map((kind) => ({ kind, packages: byKind(kind) })).filter((g) => g.packages.length > 0);
  const nocs = byKind("nocs");
  const components: ComponentUpdate[] = [];
  for (const kind of ["indi", "phd2"] as const) {
    const listed = byKind(kind);
    if (listed.length === 0) continue;
    const main = MAIN[kind].map((name) => listed.find((p) => p.name === name)).find((p) => p !== undefined);
    const named = main ?? listed[0]!;
    const [from, to] = versions(named.from, named.to);
    components.push({ kind, from, to, count: listed.length });
  }
  const system = byKind("system");
  return {
    total: packages.length,
    nocs: nocs.find((p) => p.name === "nocs") ?? nocs[0] ?? null,
    components,
    system: { count: system.length, security: system.filter((p) => p.security).length },
    reboot: packages.some((p) => p.reboot),
    groups,
  };
}

// What an install upgraded: what it was to upgrade, less what apt still lists
// (phased or kept back). The relist reads the lists the install used, so a package
// still listed was not upgraded, whatever version it is listed at now.
export function installedCount(upgraded: UpgradablePackage[], left: UpgradablePackage[]): number {
  const still = new Set(left.map((p) => p.name));
  return upgraded.filter((p) => !still.has(p.name)).length;
}

// A Debian version as people know it: no epoch ("1:"), no packaging suffix
// ("+202610040455~ubuntu26.04.1") or revision ("-0ppa1~ubuntu26.04").
export function shortVersion(version: string): string {
  let v = version.replace(/^\d+:/, "");
  v = v.split("+")[0]!;
  const hyphen = v.lastIndexOf("-");
  return hyphen > 0 ? v.slice(0, hyphen) : v;
}

// Both versions shortened, unless that makes them the same (a rebuild).
export function versions(from: string, to: string): [string, string] {
  const [a, b] = [shortVersion(from), shortVersion(to)];
  return a === b ? [from, to] : [a, b];
}

// "10:48" today, a date as well on other days: a check days old should look it.
export function isToday(iso: string, now: Date = new Date()): boolean {
  const at = new Date(iso);
  return (
    at.getFullYear() === now.getFullYear() && at.getMonth() === now.getMonth() && at.getDate() === now.getDate()
  );
}
