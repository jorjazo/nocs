import { apiFetch } from "../client";
import type {
  CoolBody,
  DeviceView,
  ExposeBody,
  MoveBody,
  SelectSlotBody,
  SlewBody,
} from "../types";

export const devicesApi = {
  list: () => apiFetch<DeviceView[]>("/api/devices"),
  connect: (id: string) =>
    apiFetch<void>(`/api/devices/${encodeURIComponent(id)}/connect`, { method: "POST" }),
  disconnect: (id: string) =>
    apiFetch<void>(`/api/devices/${encodeURIComponent(id)}/disconnect`, { method: "POST" }),
  slew: (id: string, body: SlewBody) =>
    apiFetch<void>(`/api/mounts/${encodeURIComponent(id)}/slew`, { method: "POST", body }),
  sync: (id: string, body: SlewBody) =>
    apiFetch<void>(`/api/mounts/${encodeURIComponent(id)}/sync`, { method: "POST", body }),
  park: (id: string) =>
    apiFetch<void>(`/api/mounts/${encodeURIComponent(id)}/park`, { method: "POST" }),
  expose: (id: string, body: ExposeBody) =>
    apiFetch<void>(`/api/cameras/${encodeURIComponent(id)}/expose`, { method: "POST", body }),
  cool: (id: string, body: CoolBody) =>
    apiFetch<void>(`/api/cameras/${encodeURIComponent(id)}/cool`, { method: "POST", body }),
  selectSlot: (id: string, body: SelectSlotBody) =>
    apiFetch<void>(`/api/filterwheels/${encodeURIComponent(id)}/select`, { method: "POST", body }),
  move: (id: string, body: MoveBody) =>
    apiFetch<void>(`/api/focusers/${encodeURIComponent(id)}/move`, { method: "POST", body }),
};
