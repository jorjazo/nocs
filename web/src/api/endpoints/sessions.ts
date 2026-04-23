import { apiFetch } from "../client";
import type { SessionCreated, SessionDetail, SessionRow } from "../types";

export const sessionsApi = {
  list: () => apiFetch<SessionRow[]>("/api/sessions"),
  get: (id: number) => apiFetch<SessionDetail>(`/api/sessions/${id}`),
  open: (name: string) =>
    apiFetch<SessionCreated>("/api/sessions", { method: "POST", body: { name } }),
  close: (id: number) =>
    apiFetch<{ status: string }>(`/api/sessions/${id}/close`, { method: "POST" }),
};
