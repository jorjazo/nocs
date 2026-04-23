import { apiFetch } from "../client";
import type { InstallProgressView, InstallStatusView, SolveResponse } from "../types";

export interface SolveBody {
  image_id: number;
  ra_hint_hours?: number | null;
  dec_hint_deg?: number | null;
  radius_deg?: number | null;
  scale_hint_arcsec_per_pixel?: number | null;
  timeout_sec?: number | null;
}

export const plateSolvingApi = {
  solve: (body: SolveBody) =>
    apiFetch<SolveResponse>("/api/platesolving/solve", { method: "POST", body }),
  installStatus: () => apiFetch<InstallStatusView>("/api/platesolving/install"),
  installProgress: () => apiFetch<InstallProgressView>("/api/platesolving/install/progress"),
  startInstall: (acceptLicense: boolean) =>
    apiFetch<void>("/api/platesolving/install", { method: "POST", body: { acceptLicense } }),
};
