import { apiBlob, apiFetch } from "../client";
import type { ImageView } from "../types";

export interface ImageListFilters {
  device?: string;
  session_id?: number;
  target?: string;
  filter?: string;
  limit?: number;
  offset?: number;
}

function qs(filters: ImageListFilters): string {
  const p = new URLSearchParams();
  Object.entries(filters).forEach(([k, v]) => {
    if (v !== undefined && v !== null && v !== "") p.set(k, String(v));
  });
  const s = p.toString();
  return s ? `?${s}` : "";
}

export const imagesApi = {
  list: (filters: ImageListFilters = {}) => apiFetch<ImageView[]>(`/api/images${qs(filters)}`),
  get: (id: number) => apiFetch<ImageView>(`/api/images/${id}`),
  delete: (id: number) => apiFetch<void>(`/api/images/${id}`, { method: "DELETE" }),
  downloadFits: async (id: number, filename: string) => {
    const blob = await apiBlob(`/api/images/${id}.fits`);
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
  },
};
