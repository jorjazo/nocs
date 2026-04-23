import { apiFetch } from "../client";
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
};
