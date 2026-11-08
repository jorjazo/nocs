// Interpretation of the equipment state shared by several screens.

import type { Tone } from "../components/Chip.svelte";
import type { IconName } from "../components/icons";
import type { ConnectionName, DeviceStatusName, EquipmentState, Role, RoleState } from "./types";

export const ROLES: readonly Role[] = [
  "mount",
  "main_camera",
  "filter_wheel",
  "focuser",
  "guide_camera",
  "power",
  "weather",
];

export const ROLE_ICONS: Record<Role, IconName> = {
  main_camera: "camera",
  guide_camera: "camera",
  mount: "mount",
  focuser: "focus",
  filter_wheel: "filter",
  power: "power",
  weather: "weather",
};

export function roleTone(status: DeviceStatusName, connection: ConnectionName): Tone {
  switch (status) {
    case "ready":
      return "ok";
    case "connecting":
    case "waiting":
      return "accent";
    case "error":
      return "error";
    case "unresponsive":
      return "warning";
    case "disconnected":
      // Expected while the equipment is off; lost while it should be on.
      return connection === "connected" ? "error" : "neutral";
  }
}

export function connectionTone(connection: ConnectionName): Tone {
  return connection === "connected" ? "ok" : connection === "disconnected" ? "neutral" : "accent";
}

// The roles of the active profile in display order.
export function roles(equipment: EquipmentState): [Role, RoleState][] {
  return ROLES.flatMap((role): [Role, RoleState][] => {
    const device = equipment.devices[role];
    return device ? [[role, device]] : [];
  });
}

export function readyCount(equipment: EquipmentState): { ready: number; total: number } {
  const all = roles(equipment);
  return { ready: all.filter(([, device]) => device.status === "ready").length, total: all.length };
}
