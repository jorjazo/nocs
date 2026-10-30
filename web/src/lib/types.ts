// Wire and state types. Most come generated from the server's JSON Schema
// (src/lib/generated, `pnpm gen:types`); this module adds the few refinements
// JSON Schema cannot express precisely.

import type * as Api from "./generated/api";

export type {
  AppState,
  AuthStatus,
  BlobInfo,
  CameraRoleName,
  CameraSettingsRequest,
  CameraState,
  ConnectionName,
  ConnectRequest,
  CoolingRequest,
  DeviceStatusName,
  EquipmentState,
  ExposeRequest,
  FrameInfo,
  FrameTypeName,
  Health,
  Hello,
  IndiDevice,
  IndiMessage,
  IndiNumberElement,
  IndiProperty,
  IndiServer,
  IndiState,
  IndiValueElement,
  JobInfo,
  JobStarted,
  LoopRequest,
  ObserverRequest,
  Optics,
  PairedDevice,
  PairRequest,
  Preview,
  Profile,
  PropertyStateName as PropertyState,
  Region,
  Role,
  RoleState,
  SensorInfo,
  SetPropertyRequest,
  StorageDestination,
  StorageState,
} from "./generated/api";

export type Json = null | boolean | number | string | Json[] | { [key: string]: Json };

export type IndiElement = Api.IndiNumberElement | Api.IndiValueElement;

export type PatchOp = Omit<Api.PatchOp, "value"> & { value?: Json };

export type SnapshotMessage = Omit<Api.SnapshotMessage, "state"> & { state: Record<string, Json> };
export type PatchMessage = Omit<Api.PatchMessage, "ops"> & { ops: PatchOp[] };
export type ServerMessage = SnapshotMessage | PatchMessage;
