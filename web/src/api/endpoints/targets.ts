import { apiFetch } from "../client";
import type { TargetSearchResult } from "../types";

export const targetsApi = {
  search: (q: string, limit = 20) =>
    apiFetch<TargetSearchResult[]>(`/api/targets/search?q=${encodeURIComponent(q)}&limit=${limit}`),
  get: (id: string) => apiFetch<TargetSearchResult>(`/api/targets/${encodeURIComponent(id)}`),
  addCustom: (body: { name: string; raJ2000Deg: number; decJ2000Deg: number; notes?: string }) =>
    apiFetch<{ id: number; targetId: string }>("/api/targets/custom", { method: "POST", body }),
};
