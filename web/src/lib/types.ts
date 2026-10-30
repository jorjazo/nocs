// Wire types mirrored from server/src/nocs/api/schemas.py and the state layout of
// services/indi_bridge.py. To be generated from the server's JSON Schema later.

export type Json = null | boolean | number | string | Json[] | { [key: string]: Json };

export interface PatchOp {
  op: "set" | "delete";
  path: string[];
  value?: Json;
}

export type ServerMessage =
  | { type: "snapshot"; epoch: string; version: number; state: Record<string, Json> }
  | { type: "patch"; version: number; ops: PatchOp[] };

export type PropertyType = "text" | "number" | "switch" | "light" | "blob";
export type PropertyState = "Idle" | "Ok" | "Busy" | "Alert";

export interface IndiElement {
  label: string;
  value: string | number | boolean | { format: string; size: number };
  format?: string;
  min?: number;
  max?: number;
  step?: number;
}

export interface IndiProperty {
  type: PropertyType;
  label: string;
  group: string;
  state: PropertyState;
  perm: "ro" | "wo" | "rw";
  rule: "OneOfMany" | "AtMostOne" | "AnyOfMany" | null;
  timestamp: string | null;
  message: string | null;
  elements: Record<string, IndiElement>;
}

export interface IndiDevice {
  properties: Record<string, IndiProperty>;
}

export interface IndiState {
  server?: { host: string; port: number; connected: boolean; error: string | null };
  devices?: Record<string, IndiDevice>;
  messages?: { device: string | null; timestamp: string | null; text: string }[];
}
