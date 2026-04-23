import { apiFetch } from "../client";

export const configApi = {
  getAll: () => apiFetch<Record<string, string>>("/api/config"),
  patch: (body: Record<string, string>) =>
    apiFetch<Record<string, string>>("/api/config", { method: "PATCH", body }),
};
