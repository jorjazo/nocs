// Rig's sections (docs/ux.md §7, "Rig"): which ones there are, which start open,
// how their open state is kept in the browser, and what in each needs attention,
// so that a problem shows in a closed section's header and on the Rig tab.

import type {
  AppState,
  EquipmentState,
  IndiServer,
  NetworkState,
  ShareState,
  SitesState,
  StorageState,
  SystemState,
  UpdatesState,
} from "./types.ts";
import { summarize } from "./updates.ts";

export const RIG_SECTIONS = [
  "trains",
  "devices",
  "site",
  "system",
  "storage",
  "network",
  "tailscale",
  "updates",
  "access",
  "screen",
] as const;
export type RigSection = (typeof RIG_SECTIONS)[number];

// Only the devices are open on a first visit: the rest is looked at now and then.
export const OPEN_BY_DEFAULT: readonly RigSection[] = ["devices"];

export function isRigSection(value: string): value is RigSection {
  return (RIG_SECTIONS as readonly string[]).includes(value);
}

export type OpenSections = Record<string, boolean>;

// What the browser kept, tolerating anything: storage written by an older version
// or by hand must not break the screen.
export function parseOpen(stored: string | null): OpenSections {
  if (!stored) return {};
  try {
    const value: unknown = JSON.parse(stored);
    if (typeof value !== "object" || value === null || Array.isArray(value)) return {};
    return Object.fromEntries(
      Object.entries(value as Record<string, unknown>).filter(
        (entry): entry is [string, boolean] => typeof entry[1] === "boolean",
      ),
    );
  } catch {
    return {};
  }
}

export function isOpen(open: OpenSections, section: RigSection): boolean {
  return open[section] ?? OPEN_BY_DEFAULT.includes(section);
}

// -- Attention ----------------------------------------------------------------------

// "problem": something is wrong and needs the owner; "warning": worth a look.
export type Attention = "problem" | "warning";

export function devicesAttention(
  equipment: EquipmentState | null | undefined,
  server: IndiServer | null | undefined,
): Attention | null {
  if (equipment?.error) return "problem";
  if (server && (!server.connected || !server.responsive)) return "problem";
  if (equipment?.connection !== "connected") return null;
  const devices = Object.values(equipment.devices);
  if (devices.some((device) => device.status === "error" || device.status === "disconnected")) return "problem";
  return devices.some((device) => device.status === "unresponsive") ? "warning" : null;
}

export function storageAttention(
  storage: StorageState | null | undefined,
  share: ShareState | null | undefined,
): Attention | null {
  if (storage && (storage.error || storage.destination === null)) return "problem";
  if (storage?.unmounted.some((drive) => drive.error)) return "warning";
  if (share?.on && !share.running) return "warning";
  return null;
}

export function systemAttention(system: SystemState | null | undefined): Attention | null {
  const warnings = system?.health?.warnings ?? [];
  if (warnings.includes("under_voltage")) return "problem";
  // Not system.error: on a PC nocs-system does not run, and that is no fault.
  return warnings.length > 0 ? "warning" : null;
}

// Not a failed join: nocs-system keeps the last one until the next, across restarts,
// so one mistyped password would light the tab for good. The section says it.
export function networkAttention(network: NetworkState | null | undefined, owner: boolean): Attention | null {
  return network && owner && network.ap_default_password ? "warning" : null;
}

// Without an active site there is no night, no go to and no FITS position.
export function siteAttention(sites: SitesState | null | undefined): Attention | null {
  return sites && sites.active === null ? "warning" : null;
}

// Updates worth a dot on the tab: a new NOCS, or security fixes. Plain system
// updates come every few days, and a dot that never goes away says nothing.
export function updatesWorthIt(updates: UpdatesState | null | undefined): boolean {
  if (!updates) return false;
  if (updates.reboot_required) return true;
  const summary = summarize(updates.packages);
  return summary.nocs !== null || summary.system.security > 0;
}

// The dot on the Rig tab: a problem anywhere on Rig, else updates for the owner.
export function rigAttention(app: AppState, owner: boolean): Attention | "updates" | null {
  const all = [
    devicesAttention(app.equipment, app.indi?.server),
    storageAttention(app.storage, app.share),
    systemAttention(app.system),
    networkAttention(app.network, owner),
    siteAttention(app.sites),
  ];
  if (all.includes("problem")) return "problem";
  if (all.includes("warning")) return "warning";
  return owner && updatesWorthIt(app.updates) ? "updates" : null;
}
