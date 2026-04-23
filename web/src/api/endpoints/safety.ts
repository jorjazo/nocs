import { apiFetch } from "../client";
import type { SafetyStatusView } from "../types";

export interface SensorReadingBody {
  sensor: string;
  ts?: string;
  values: Record<string, number | string | boolean>;
}

export interface ActiveTargetBody {
  targetId: string;
  raJ2000Deg: number;
  decJ2000Deg: number;
}

export const safetyApi = {
  status: () => apiFetch<SafetyStatusView>("/api/safety/rules"),
  reload: () => apiFetch<{ rules: number }>("/api/safety/rules/reload", { method: "POST" }),
  eStop: (reason?: string) =>
    apiFetch<{ status: string }>("/api/safety/e-stop", {
      method: "POST",
      body: reason ? { reason } : {},
    }),
  reset: () => apiFetch<{ status: string }>("/api/safety/reset", { method: "POST" }),
  postReading: (body: SensorReadingBody) =>
    apiFetch<{ status: string }>("/api/safety/sensors/readings", { method: "POST", body }),
  setActiveTarget: (body: ActiveTargetBody) =>
    apiFetch<{ status: string }>("/api/safety/active-target", { method: "POST", body }),
};
