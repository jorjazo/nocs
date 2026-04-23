import { apiFetch } from "../client";
import type { ObservatoryView } from "../types";

export interface CreateObservatoryBody {
  name: string;
  latitudeDeg: number;
  longitudeDeg: number;
  elevationM: number;
  timezone: string;
  horizonMaskJson?: string | null;
}

export type UpdateObservatoryBody = Partial<CreateObservatoryBody>;

export const observatoriesApi = {
  list: () => apiFetch<ObservatoryView[]>("/api/observatories"),
  get: (id: number) => apiFetch<ObservatoryView>(`/api/observatories/${id}`),
  create: (body: CreateObservatoryBody) =>
    apiFetch<ObservatoryView>("/api/observatories", { method: "POST", body }),
  update: (id: number, body: UpdateObservatoryBody) =>
    apiFetch<ObservatoryView>(`/api/observatories/${id}`, { method: "PATCH", body }),
  activate: (id: number) =>
    apiFetch<{ id: number; active: boolean }>(`/api/observatories/${id}/activate`, {
      method: "POST",
    }),
  delete: (id: number) =>
    apiFetch<{ id: number; deleted: boolean }>(`/api/observatories/${id}`, { method: "DELETE" }),
};
