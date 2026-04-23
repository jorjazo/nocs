import { apiFetch } from "../client";
import type { SequenceDefinitionDto, SequenceView } from "../types";

export interface SequenceListFilters {
  session_id?: number;
  limit?: number;
  offset?: number;
}

function qs(f: SequenceListFilters): string {
  const p = new URLSearchParams();
  Object.entries(f).forEach(([k, v]) => {
    if (v !== undefined && v !== null && v !== "") p.set(k, String(v));
  });
  const s = p.toString();
  return s ? `?${s}` : "";
}

export const sequencesApi = {
  list: (f: SequenceListFilters = {}) => apiFetch<SequenceView[]>(`/api/sequences${qs(f)}`),
  get: (id: number) => apiFetch<SequenceView>(`/api/sequences/${id}`),
  submit: (def: SequenceDefinitionDto) =>
    apiFetch<SequenceView>("/api/sequences", { method: "POST", body: def }),
  pause: (id: number) =>
    apiFetch<{ status: string }>(`/api/sequences/${id}/pause`, { method: "POST" }),
  resume: (id: number) =>
    apiFetch<{ status: string }>(`/api/sequences/${id}/resume`, { method: "POST" }),
  abort: (id: number, reason?: string) =>
    apiFetch<{ status: string }>(`/api/sequences/${id}/abort`, {
      method: "POST",
      body: reason ? { reason } : {},
    }),
};
